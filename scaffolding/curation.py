"""SAR data curation pipeline (Roadmap Task 1.2: preprocess + label).

Turns SAR intensity chips into detector-training labels, using the same
deterministic CFAR detector the runtime uses (`vision.py`). The pipeline is real
and runnable today; what it produces is deliberately not treated as ground truth.

HONEST STATUS — the labels are AUTO-CANDIDATES, not gold:
CFAR gives a strong, explainable first pass over a chip, which turns the human
labelling task from "draw every box from scratch" into "correct a proposed set".
That is the point of the step (bootstrap/weak labelling), but a candidate box is
not a verified one: the manifest marks every chip `review_status: pending`, and
no downstream training should treat these as final until a human has checked
them. Over-trusting auto-labels teaches the detector CFAR's own false positives.

Pipeline per chip:  Lee speckle filter -> CA-CFAR -> connected components
                    -> tight pixel bbox -> YOLO label (class 0 = vessel).
It also emits the georeferenced detections (the vision.py contract), which is the
bridge from a raw chip to the deterministic engine.

    python scaffolding/curation.py                     # self-check on synthetic chips
    python scaffolding/curation.py --input datasets/chips --out datasets/sar_vessels
    python scaffolding/curation.py --synthetic 8 --out datasets/sar_vessels
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np

import vision

VESSEL_CLASS = 0
CLASS_NAMES = ["vessel"]
# A default affine for synthetic chips; real chips carry their own from product
# metadata. Only used to emit georeferenced detections, never for the YOLO label.
_SYNTH_GEO = {"origin_lat": 36.90, "origin_lon": -7.20,
              "pixel_deg_lat": 0.00009, "pixel_deg_lon": 0.00011}


def _bbox_to_yolo(bbox: dict, rows: int, cols: int, pad: int = 1) -> tuple:
    """Inclusive pixel bbox -> normalised (x_center, y_center, w, h).

    A sub-15 m angula return is 1-2 px, so the box is padded slightly: a
    degenerate 1 px box trains poorly, and the true hull bleeds into neighbours.
    """
    r0 = max(0, bbox["row_min"] - pad)
    c0 = max(0, bbox["col_min"] - pad)
    r1 = min(rows - 1, bbox["row_max"] + pad)
    c1 = min(cols - 1, bbox["col_max"] + pad)
    xc = ((c0 + c1 + 1) / 2) / cols
    yc = ((r0 + r1 + 1) / 2) / rows
    w = (c1 - c0 + 1) / cols
    h = (r1 - r0 + 1) / rows
    return xc, yc, w, h


def curate_chip(image: np.ndarray, geo: dict,
                config: dict | None = None) -> tuple:
    """Return (yolo_lines, detections) for one chip. Labels are candidates."""
    image = np.asarray(image, dtype=np.float64)
    rows, cols = image.shape
    detections = vision.detect_vessels(image, geo, config)
    lines = []
    for d in detections:
        xc, yc, w, h = _bbox_to_yolo(d["pixel"]["bbox"], rows, cols)
        lines.append(f"{VESSEL_CLASS} {xc:.6f} {yc:.6f} {w:.6f} {h:.6f}")
    return lines, detections


def _load_chip(path: Path) -> np.ndarray:
    if path.suffix == ".npy":
        return np.load(path)
    raise ValueError(f"unsupported chip format {path.suffix!r} ({path}); save "
                     f"Sentinel-1 intensity chips as .npy 2-D arrays")


def _synthetic_chips(n: int, seed: int = 0):
    """Yield (name, image) synthetic SAR chips with a few injected targets."""
    rng = np.random.default_rng(seed)
    for i in range(n):
        k = int(rng.integers(2, 6))
        targets = [(int(rng.integers(20, 236)), int(rng.integers(20, 236)),
                    float(rng.integers(40, 90))) for _ in range(k)]
        yield f"synth_{i:03d}", vision.synthetic_scene(256, targets=targets,
                                                       seed=seed + i + 1)


def build_dataset(chips, out_dir: Path, geo: dict, config: dict | None = None) -> dict:
    """Write images/, labels/ and a manifest. `chips` yields (name, image)."""
    out_dir = Path(out_dir)
    img_dir = out_dir / "images"
    lbl_dir = out_dir / "labels"
    img_dir.mkdir(parents=True, exist_ok=True)
    lbl_dir.mkdir(parents=True, exist_ok=True)

    entries = []
    total_labels = 0
    for name, image in chips:
        lines, detections = curate_chip(image, geo, config)
        np.save(img_dir / f"{name}.npy", np.asarray(image, dtype=np.float32))
        (lbl_dir / f"{name}.txt").write_text("\n".join(lines) + ("\n" if lines else ""))
        total_labels += len(lines)
        entries.append({"name": name, "candidate_labels": len(lines),
                        "review_status": "pending"})

    manifest = {
        "task": "Roadmap 1.2 — SAR preprocess + label (candidate labels)",
        "label_format": "YOLO (class x_center y_center w h, normalised)",
        "classes": CLASS_NAMES,
        "labels_are": ("AUTO-CANDIDATE from CA-CFAR — a bootstrap for human "
                       "review, NOT verified ground truth. Do not train on "
                       "chips whose review_status is still 'pending' as if they "
                       "were gold."),
        "detector": "scaffolding/vision.py CA-CFAR (deterministic, auditable)",
        "chips": len(entries),
        "candidate_labels_total": total_labels,
        "entries": entries,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def _selfcheck() -> None:
    """Runnable check: synthetic chip with known targets -> valid YOLO labels."""
    truth = [(40, 60, 60), (120, 200, 45), (200, 90, 80)]
    img = vision.synthetic_scene(256, targets=truth, seed=7)
    lines, dets = curate_chip(img, _SYNTH_GEO)

    assert len(lines) >= len(truth), f"missed targets: {len(lines)} < {len(truth)}"
    for line in lines:
        parts = line.split()
        assert len(parts) == 5 and int(parts[0]) == VESSEL_CLASS
        vals = [float(x) for x in parts[1:]]
        assert all(0.0 <= v <= 1.0 for v in vals), f"YOLO value out of range: {line}"
        assert vals[2] > 0 and vals[3] > 0, f"degenerate box: {line}"
    # The label centre must land on a real detection's centroid (px -> norm).
    rows = cols = 256
    for d in dets:
        cx = d["pixel"]["col"] / cols
        assert any(abs(float(l.split()[1]) - cx) < 0.03 for l in lines), d
    print(f"curation self-check passed: {len(lines)} candidate labels from "
          f"{len(truth)} injected targets, all YOLO-valid")


def main() -> int:
    parser = argparse.ArgumentParser(description="SAR data curation (Task 1.2)")
    parser.add_argument("--input", type=Path,
                        help="directory of .npy SAR intensity chips")
    parser.add_argument("--synthetic", type=int, metavar="N",
                        help="generate N synthetic chips instead of reading --input")
    parser.add_argument("--out", type=Path, default=Path("datasets/sar_vessels"))
    args = parser.parse_args()

    if not args.input and not args.synthetic:
        _selfcheck()
        return 0

    if args.input:
        paths = sorted(p for p in args.input.glob("*.npy"))
        if not paths:
            print(f"[curation] no .npy chips in {args.input}", file=sys.stderr)
            return 1
        chips = ((p.stem, _load_chip(p)) for p in paths)
    else:
        chips = _synthetic_chips(args.synthetic)

    manifest = build_dataset(chips, args.out, _SYNTH_GEO)
    print(f"[curation] {manifest['chips']} chips, "
          f"{manifest['candidate_labels_total']} candidate labels -> {args.out}")
    print(f"[curation] REVIEW REQUIRED: labels are CFAR auto-candidates, every "
          f"chip is review_status='pending'. Correct them before training.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
