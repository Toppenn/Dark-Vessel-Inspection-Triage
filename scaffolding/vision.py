"""SAR vision module (Phase 2): detect vessel signatures in a radar scene.

This is the Step-3 detector of the agentic loop, kept strictly separate from the
LLM reasoning (roadmap instruction 3). It turns a Sentinel-1 SAR intensity chip
into vessel detections — position, length, confidence — the raw geometry that
the AIS-matching stage (Step 4) and the deterministic engine (analysis.py) then
consume. It does NOT decide AIS status or fishing behaviour; those come from
other sources and are never invented here.

WHY CFAR, NOT A FINE-TUNED CNN (yet):
The roadmap's target is a fine-tuned lightweight detector optimised with
TensorRT and served as an NVIDIA NIM. That needs a GPU, labelled SAR data and
trained weights — none of which live in this repo. Constant False Alarm Rate
(CA-CFAR) detection is the classic, pre-deep-learning SAR ship detector: bright
point targets against Rayleigh/exponential sea clutter. It is a strong baseline
that runs today on CPU with numpy alone, needs no training data, and — crucially
for an enforcement file — is DETERMINISTIC and AUDITABLE: you can explain exactly
why a pixel was flagged. The CNN/NIM backend slots in at `detect_vessels`
(see `backend`) once weights exist; its detections use the same output contract.

REAL-WORLD CEILING (deliberate):
Sentinel-1 GRD resolves ~10 m/pixel, so a sub-15 m angula boat is 1-2 pixels and
often sub-pixel. CFAR finds the bright return but the length estimate is coarse —
which is exactly why the engine carries `length_sigma_m` and treats AIS
applicability near the 15 m threshold as three-state. This detector reports a
length AND its pixel extent so that uncertainty stays visible downstream.
"""

import math

import numpy as np

# Calibration knobs (ponytail: tune these against real Sentinel-1 chips and
# labelled detections; the defaults are reasonable for ~10 m/pixel GRD).
DEFAULTS = {
    "pfa": 1e-4,            # target probability of false alarm per pixel
    "guard_radius": 2,     # guard cells around the test cell (px), excluded from bg
    "train_radius": 6,     # outer training window radius (px)
    "enl": 4.0,            # equivalent number of looks, for the Lee speckle filter
    "min_area_px": 2,      # blobs smaller than this are discarded as speckle
    "pixel_spacing_m": 10.0,   # ground spacing per pixel (Sentinel-1 IW GRD ~10 m)
}


def _box_sum(img: np.ndarray, radius: int) -> np.ndarray:
    """Sum over a (2*radius+1)^2 window centred on every pixel, same shape out.

    Reflect-pad then use a summed-area table so every window is full and the
    per-pixel count is constant — no border special-casing.
    """
    win = 2 * radius + 1
    padded = np.pad(img, radius, mode="reflect")
    ii = padded.cumsum(0).cumsum(1)
    ii = np.pad(ii, ((1, 0), (1, 0)), mode="constant")
    return (ii[win:, win:] - ii[:-win, win:] - ii[win:, :-win] + ii[:-win, :-win])


def lee_filter(img: np.ndarray, enl: float) -> np.ndarray:
    """Refined Lee speckle filter. Smooths homogeneous clutter while preserving
    point targets and edges — which is what keeps CFAR false alarms down without
    erasing the vessels we are looking for.
    """
    r = 3
    n = (2 * r + 1) ** 2
    mean = _box_sum(img, r) / n
    sq_mean = _box_sum(img * img, r) / n
    var = np.maximum(sq_mean - mean * mean, 0.0)
    cu2 = 1.0 / enl                      # noise variation coefficient, squared
    ci2 = np.divide(var, mean * mean, out=np.zeros_like(var), where=mean > 0)
    # Weight -> 1 where the local signal varies more than pure speckle (a target),
    # -> 0 in flat clutter. Clamped to [0, 1].
    weight = np.clip(1.0 - cu2 / np.maximum(ci2, 1e-9), 0.0, 1.0)
    return mean + weight * (img - mean)


def _ca_cfar_mask(img: np.ndarray, cfg: dict) -> tuple:
    """Cell-averaging CFAR. Returns (detection mask, background estimate).

    Background per pixel is the mean over a training annulus (outer window minus
    a guard window that shields the target's own energy). The threshold multiple
    `alpha` is derived from the target Pfa for exponential-intensity clutter:
    alpha = N * (Pfa**(-1/N) - 1).
    """
    guard, train = cfg["guard_radius"], cfg["train_radius"]
    if train <= guard:
        raise ValueError("train_radius must exceed guard_radius")

    outer_sum = _box_sum(img, train)
    guard_sum = _box_sum(img, guard)
    n_train = (2 * train + 1) ** 2 - (2 * guard + 1) ** 2
    background = (outer_sum - guard_sum) / n_train

    alpha = n_train * (cfg["pfa"] ** (-1.0 / n_train) - 1.0)
    mask = img > alpha * background
    return mask, background


def _label_blobs(mask: np.ndarray) -> list:
    """8-connected components of a boolean mask, via iterative flood fill.

    numpy only — scipy.ndimage.label would do this but is not a dependency here,
    and a SAR chip has few above-threshold pixels so an explicit fill is cheap.
    """
    seen = np.zeros_like(mask, dtype=bool)
    rows, cols = mask.shape
    blobs = []
    neighbours = [(-1, -1), (-1, 0), (-1, 1), (0, -1),
                  (0, 1), (1, -1), (1, 0), (1, 1)]
    for r0, c0 in zip(*np.nonzero(mask)):
        if seen[r0, c0]:
            continue
        stack = [(r0, c0)]
        seen[r0, c0] = True
        pixels = []
        while stack:
            r, c = stack.pop()
            pixels.append((r, c))
            for dr, dc in neighbours:
                rr, cc = r + dr, c + dc
                if 0 <= rr < rows and 0 <= cc < cols and mask[rr, cc] and not seen[rr, cc]:
                    seen[rr, cc] = True
                    stack.append((rr, cc))
        blobs.append(pixels)
    return blobs


def _pixel_to_lonlat(row: float, col: float, geo: dict) -> tuple:
    """Affine pixel -> geographic. Row increases southward from the top-left
    origin, matching how a north-up SAR raster is stored."""
    lon = geo["origin_lon"] + col * geo["pixel_deg_lon"]
    lat = geo["origin_lat"] - row * geo["pixel_deg_lat"]
    return round(lat, 5), round(lon, 5)


def detect_vessels(image: np.ndarray, geo: dict, config: dict | None = None,
                   backend: str = "cfar") -> list:
    """Detect vessel signatures in a SAR intensity chip.

    Args:
        image: 2-D SAR intensity (linear power), north-up.
        geo:   {origin_lat, origin_lon, pixel_deg_lat, pixel_deg_lon}, the
               affine that georeferences pixel (0,0) at the top-left.
        config: overrides for DEFAULTS (the calibration knobs).
        backend: "cfar" today. A trained CNN served via TensorRT/NIM slots in
                 here later, returning the same list of detection dicts.

    Returns a list of detections, each:
        {id, lat, lon, estimated_length_m, detection_confidence,
         pixel: {row, col, area_px}}
    AIS status and fishing behaviour are deliberately absent: this is the
    detector, not the fusion stage.
    """
    if backend != "cfar":
        raise NotImplementedError(
            f"backend {backend!r} not available; train weights and add it here")
    cfg = {**DEFAULTS, **(config or {})}
    img = np.asarray(image, dtype=np.float64)
    if img.ndim != 2:
        raise ValueError(f"expected a 2-D SAR chip, got shape {img.shape}")

    filtered = lee_filter(img, cfg["enl"])
    mask, background = _ca_cfar_mask(filtered, cfg)

    detections = []
    for i, pixels in enumerate(_label_blobs(mask), start=1):
        if len(pixels) < cfg["min_area_px"]:
            continue
        rr = np.array([p[0] for p in pixels])
        cc = np.array([p[1] for p in pixels])
        # Intensity-weighted centroid: the brightest scatterers dominate, which
        # is where the hull actually is.
        w = img[rr, cc]
        row_c = float((rr * w).sum() / w.sum())
        col_c = float((cc * w).sum() / w.sum())
        lat, lon = _pixel_to_lonlat(row_c, col_c, geo)

        # Coarse length: the blob's largest extent in ground metres. Sub-pixel at
        # Sentinel-1 resolution, hence reported alongside the pixel area so the
        # engine's length-uncertainty band stays honest.
        extent_px = max(rr.max() - rr.min(), cc.max() - cc.min()) + 1
        length_m = round(extent_px * cfg["pixel_spacing_m"], 1)

        # Confidence: peak return over local clutter (SNR), squashed to (0, 1).
        peak_snr = float((img[rr, cc] / background[rr, cc]).max())
        confidence = round(1.0 - math.exp(-peak_snr / 10.0), 3)

        detections.append({
            "id": f"S1-{i:03d}",
            "lat": lat,
            "lon": lon,
            "estimated_length_m": length_m,
            "detection_confidence": confidence,
            "pixel": {"row": round(row_c, 1), "col": round(col_c, 1),
                      "area_px": len(pixels),
                      # Tight pixel bbox (inclusive), so the curation step can
                      # emit a detector-training label without recomputing blobs.
                      "bbox": {"row_min": int(rr.min()), "row_max": int(rr.max()),
                               "col_min": int(cc.min()), "col_max": int(cc.max())}},
        })
    return detections


# --- Synthetic scene generator, for the self-check and the demo only. --------
# Clearly synthetic: real chips come from the Copernicus Data Space Ecosystem.
def synthetic_scene(size: int = 256, targets: list | None = None,
                    clutter_mean: float = 1.0, seed: int = 0) -> np.ndarray:
    """Exponential sea clutter (single-look SAR intensity) with bright point
    targets injected at given (row, col) pixels."""
    rng = np.random.default_rng(seed)
    img = rng.exponential(clutter_mean, size=(size, size))
    for r, c, amp in (targets or []):
        img[r, c] += amp
        # A little energy bleeds into neighbours, as a real hull would.
        for dr, dc in ((0, 1), (1, 0), (0, -1), (-1, 0)):
            if 0 <= r + dr < size and 0 <= c + dc < size:
                img[r + dr, c + dc] += amp * 0.4
    return img


def _demo() -> None:
    truth = [(40, 60, 60), (120, 200, 45), (200, 90, 80), (75, 150, 55)]
    img = synthetic_scene(256, targets=truth, seed=7)
    geo = {"origin_lat": 36.90, "origin_lon": -7.20,
           "pixel_deg_lat": 0.00009, "pixel_deg_lon": 0.00011}

    dets = detect_vessels(img, geo)

    # Every injected target is recovered within a couple of pixels of its centre.
    def matched(tr, tc):
        return any(abs(d["pixel"]["row"] - tr) <= 2 and abs(d["pixel"]["col"] - tc) <= 2
                   for d in dets)

    hits = sum(matched(r, c) for r, c, _ in truth)
    assert hits == len(truth), f"recovered {hits}/{len(truth)} targets: {dets}"
    # False alarms stay low: CFAR + Lee keep clutter under control.
    assert len(dets) <= len(truth) + 1, f"too many false alarms: {len(dets)}"
    # Georeferencing runs and lands in the scene's geographic footprint.
    assert all(36.87 <= d["lat"] <= 36.90 and -7.20 <= d["lon"] <= -7.17
               for d in dets), dets

    print(f"vision self-check passed: recovered {hits}/{len(truth)} targets, "
          f"{len(dets)} detections total")
    for d in dets:
        print(f"  {d['id']}  {d['lat']}, {d['lon']}  "
              f"~{d['estimated_length_m']} m  conf {d['detection_confidence']}  "
              f"(px {d['pixel']['row']},{d['pixel']['col']} area {d['pixel']['area_px']})")


if __name__ == "__main__":
    _demo()
