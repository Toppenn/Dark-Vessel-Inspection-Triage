"""Data loading.

The whole system is built so that going live changes only this file: as long as
these loaders return the documented shape, nothing downstream moves.

  load_detections  -> local synthetic JSON (default) OR live Global Fishing Watch
                      SAR vessel detections (source="gfw")
  load_zones       -> local regulatory layer (Natura 2000 / WDPA to come)

Planned real sources:
  detections -> Global Fishing Watch, "Vessel detections from Sentinel-1 SAR"
                (implemented below), or the xView3 benchmark
  zones      -> Natura 2000 marine, WDPA, marine reserves of fishing interest,
                seasonal closures published in official bulletins
  raw imagery -> Copernicus Data Space Ecosystem (Sentinel-1), fed to
                scaffolding/vision.py if we run our own detector instead of GFW's
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "demo_data"

# Global Fishing Watch API v3. Base URL and Bearer auth are standard; the SAR
# detections dataset id depends on the access you were granted — set GFW_DATASET.
GFW_BASE_URL = os.environ.get("GFW_BASE_URL",
                              "https://gateway.api.globalfishingwatch.org")


def load_zones(filename: str = "zones.json") -> dict:
    """Regulatory layer: zones, prohibited gear, closures and configuration."""
    with open(DATA_DIR / filename, encoding="utf-8") as f:
        return json.load(f)


def _load_local_detections(filename: str) -> dict:
    with open(DATA_DIR / filename, encoding="utf-8") as f:
        return json.load(f)


def load_detections(filename: str = "detections.json",
                    source: str = "local", **gfw_kwargs) -> dict:
    """Radar detections for one scene, including AIS matching.

    source="local" (default) reads the synthetic demo file — unchanged behaviour.
    source="gfw" pulls live SAR vessel detections from Global Fishing Watch and,
    on any failure (no token, network error, empty result), falls back to the
    local file so a demo never dies on a missing credential.
    """
    if source == "gfw":
        return load_detections_gfw(fallback=filename, **gfw_kwargs)
    return _load_local_detections(filename)


# --- Global Fishing Watch adapter -------------------------------------------
#
# THE ONE SEAM TO CONFIRM AGAINST YOUR GRANTED ACCESS: `_gfw_request` (the
# dataset id, path and query-parameter names) and the field names read in
# `_gfw_to_detection`. Both are isolated here on purpose. The field names below
# follow the GFW SAR vessel-detections data model (Paolo et al. 2024): each
# detection carries a position, an estimated length, a match category against
# AIS, and a fishing-behaviour score. Adjust the keys if your product differs.

# Gulf of Cadiz demo footprint (min_lon, min_lat, max_lon, max_lat), so the
# adapter is runnable out of the box; override via the `region` argument.
_DEMO_REGION = (-7.40, 36.20, -6.50, 37.15)


def load_detections_gfw(region=None, start=None, end=None,
                        fallback: str = "detections.json") -> dict:
    """Fetch SAR vessel detections from GFW and map them to the scene schema.

    Args:
        region: (min_lon, min_lat, max_lon, max_lat). Defaults to the demo area.
        start, end: ISO date strings bounding the scene. Defaults to the last
            full day, which is a reasonable "most recent scene" for a demo.
        fallback: local file used if the fetch cannot be completed.
    """
    token = os.environ.get("GFW_TOKEN")
    if not token:
        print("[data] GFW_TOKEN not set — falling back to local detections. "
              "Get a token at globalfishingwatch.org/our-apis and "
              "`export GFW_TOKEN=...` to pull live data.")
        return _load_local_detections(fallback)

    region = region or _DEMO_REGION
    end = end or date.today().isoformat()
    start = start or (date.fromisoformat(end) - timedelta(days=1)).isoformat()

    try:
        entries = _gfw_request(region, start, end, token)
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError,
            TimeoutError) as exc:
        print(f"[data] GFW request failed ({exc}); falling back to local "
              f"detections.")
        return _load_local_detections(fallback)

    detections, skipped = [], 0
    for i, entry in enumerate(entries):
        record = _gfw_to_detection(entry, i)
        if record is None:
            skipped += 1
            continue
        detections.append(record)

    if skipped:
        # Reported, never hidden: a dropped detection is a vessel we did not
        # look at. Data-quality drops must be visible, like every omission here.
        print(f"[data] GFW: skipped {skipped} detection(s) missing "
              f"position, length or behaviour score.")

    if not detections:
        print("[data] GFW returned no usable detections; falling back to local.")
        return _load_local_detections(fallback)

    return {
        "_note": (f"LIVE Global Fishing Watch SAR detections, {start}..{end}, "
                  f"bbox {region}."),
        "scene": {
            "source": "Sentinel-1 (GFW SAR detections)",
            "mode": "IW / VV-VH",
            "timestamp": f"{end}T00:00:00Z",
            "area": f"bbox {region}",
        },
        "detections": detections,
    }


def _gfw_request(region, start: str, end: str, token: str) -> list:
    """GET the SAR detections for a bbox and date range, return a list of raw
    entries.

    CONFIRM AGAINST YOUR GRANTED PRODUCT: the dataset id (GFW_DATASET), the path
    and the query-parameter names. The base URL and Bearer scheme are standard
    GFW API v3. The response envelope is normalised below to a plain list.
    """
    dataset = os.environ.get("GFW_DATASET", "public-global-sar-presence:latest")
    min_lon, min_lat, max_lon, max_lat = region
    params = {
        "datasets[0]": dataset,
        "start-date": start,
        "end-date": end,
        "bbox": f"{min_lon},{min_lat},{max_lon},{max_lat}",
        "limit": os.environ.get("GFW_LIMIT", "500"),
    }
    path = os.environ.get("GFW_PATH", "/v3/sar/detections")
    url = f"{GFW_BASE_URL}{path}?{urllib.parse.urlencode(params)}"

    request = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
        payload = json.loads(response.read().decode("utf-8"))

    # GFW responses wrap the rows under one of these keys depending on endpoint;
    # accept a bare list too.
    if isinstance(payload, list):
        return payload
    for key in ("entries", "data", "features"):
        if isinstance(payload.get(key), list):
            return payload[key]
    raise ValueError(f"unexpected GFW response shape: keys={list(payload)[:5]}")


def _first(entry: dict, *keys):
    """Return the first present, non-null value among candidate field names.

    GFW field names vary a little across products/versions; listing the likely
    aliases in one place is cheaper than pinning to one spelling that may change.
    """
    for key in keys:
        if entry.get(key) is not None:
            return entry[key]
    # GFW GeoJSON features carry the attributes under "properties".
    props = entry.get("properties")
    if isinstance(props, dict):
        for key in keys:
            if props.get(key) is not None:
                return props[key]
    return None


def _as_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _gfw_to_detection(entry: dict, idx: int):
    """Map one GFW SAR detection to a detection record, or None to skip it.

    Skips only on missing position/length/behaviour — the fields the engine
    genuinely needs. Everything about the duty of caution is preserved here:
    AIS status is set ONLY when GFW is confident, so an ambiguous match becomes
    'unknown' downstream (never 'dark'), exactly as the engine expects.
    """
    lat = _as_float(_first(entry, "detect_lat", "lat", "latitude"))
    lon = _as_float(_first(entry, "detect_lon", "lon", "longitude"))
    length = _as_float(_first(entry, "length_m", "estimated_length_m", "length"))
    if lat is None or lon is None or length is None:
        return None

    record = {
        "id": str(_first(entry, "id", "detect_id", "detection_id")
                  or f"GFW-{idx:04d}"),
        "lat": lat,
        "lon": lon,
        "estimated_length_m": length,
    }

    # Behaviour score. The engine requires it and REFUSES to read a missing score
    # as "not fishing" (that would silently suppress zone indicators). Map GFW's
    # fishing probability if present; accept a boolean/category as a fallback;
    # skip the detection if neither exists rather than invent activity.
    fishing = _as_float(_first(entry, "fishing_score", "score"))
    if fishing is None:
        flag = _first(entry, "is_fishing", "fishing")
        category = str(_first(entry, "vessel_class", "matched_category") or "").lower()
        if isinstance(flag, bool):
            fishing = 1.0 if flag else 0.0
        elif "fishing" in category:
            fishing = 1.0
        else:
            return None
    record["fishing_score"] = fishing

    # AIS match. matched -> broadcasting (True); unmatched -> dark (False);
    # anything else (possibly/likely/absent) -> OMIT the field, so the engine
    # treats it as 'unknown' and never as evidence of darkness. This is the
    # duty of caution enforced at the data boundary.
    matched = str(_first(entry, "matched_category", "match_category",
                         "matched") or "").lower()
    if matched in ("matched", "true"):
        record["ais_matched"] = True
        mmsi = _first(entry, "mmsi", "ssvid")
        if mmsi is not None:
            record["mmsi"] = str(mmsi)
        for src, dst in (("vessel_name", "vessel_name"), ("shipname", "vessel_name"),
                         ("flag", "flag")):
            value = _first(entry, src)
            if value is not None:
                record[dst] = value
    elif matched in ("unmatched", "false"):
        record["ais_matched"] = False
    # else: leave ais_matched unset -> 'unknown'

    # Gear is registry-derived and only meaningful for matched vessels; for
    # unmatched SAR detections it is unknown, which the engine treats as context,
    # never as an indicator.
    gear = _first(entry, "likely_gear", "geartype", "vessel_class")
    record["likely_gear"] = str(gear) if (gear and record.get("ais_matched")) \
        else "unknown"

    speed = _as_float(_first(entry, "speed_kn", "speed"))
    if speed is not None:
        record["speed_kn"] = speed
    return record


def _demo() -> None:
    """Self-check for the mapping — the part that must be right and needs no
    network. Proves the mapped output is consumable by the engine unchanged."""
    import analysis  # local import: no module-level cycle, test-only

    entries = [
        # matched, broadcasting, with identity and a fishing probability
        {"id": "A", "detect_lat": 36.7, "detect_lon": -7.0, "length_m": 34.0,
         "matched_category": "matched", "fishing_score": 0.9, "mmsi": "224000",
         "shipname": "REAL VESSEL", "flag": "ESP", "geartype": "trawlers"},
        # unmatched (dark), score as boolean flag
        {"id": "B", "lat": 36.5, "lon": -6.75, "length_m": 22.0,
         "matched_category": "unmatched", "is_fishing": True},
        # ambiguous match -> ais unset (unknown), GeoJSON 'properties' envelope
        {"properties": {"detect_lat": 36.6, "detect_lon": -6.9, "length_m": 18.0,
                        "matched_category": "possibly", "fishing_score": 0.8}},
        # missing length -> skipped
        {"detect_lat": 36.4, "detect_lon": -6.7, "matched_category": "unmatched",
         "fishing_score": 0.5},
        # no behaviour signal at all -> skipped (never assumed 'not fishing')
        {"detect_lat": 36.3, "detect_lon": -6.6, "length_m": 12.0,
         "matched_category": "unmatched"},
    ]
    mapped = [r for r in (_gfw_to_detection(e, i) for i, e in enumerate(entries))
              if r is not None]

    assert len(mapped) == 3, [m["id"] for m in mapped]
    a, b, c = mapped
    assert a["ais_matched"] is True and a["mmsi"] == "224000" and a["flag"] == "ESP"
    assert a["likely_gear"] == "trawlers"
    assert b["ais_matched"] is False and b["fishing_score"] == 1.0
    assert b["likely_gear"] == "unknown"          # unmatched -> gear is unknown
    assert "ais_matched" not in c                 # ambiguous -> unknown, not dark
    assert c["estimated_length_m"] == 18.0

    # The decisive proof: feed the mapped scene through the real engine.
    scene = {"scene": {"timestamp": "2026-07-18T06:12:00Z", "area": "test"},
             "detections": mapped}
    dossier = analysis.analyse(load_zones(), scene)
    assert dossier["total_detections"] == 3
    unknown = next(r for r in dossier["records"] if r["id"] == mapped[2]["id"])
    assert unknown["ais_status"] == "unknown"     # not 'dark' — duty of caution

    print(f"data self-check passed: mapped {len(mapped)}/5 entries "
          f"(2 skipped), engine consumed them; ambiguous match -> "
          f"{unknown['ais_status']}")


if __name__ == "__main__":
    _demo()
