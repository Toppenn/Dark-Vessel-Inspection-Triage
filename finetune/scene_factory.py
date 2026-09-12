"""Synthetic SCENE generator — the structured half of the synthetic data.

Why this exists, and why it is not an LLM:

The training input for the writer agent is a *factual dossier*. In this system
the dossier is ground truth by construction: every figure in it was computed by
`src/analysis.py` from detections and a regulatory layer. If a language model
invented the dossier, the supervision signal would inherit the model's errors
and the whole claim of the project ("facts are computed, models interpret")
would be false at training time as well as at inference time.

So the facts are sampled here, deterministically and with a seed, and the
dossier is produced by running the real engine over them. A language model
never touches the input side. NeMo Data Designer is used for the *surface*
only — zone names, port names, vessel names, working language — see
`surface_vocab.py`.

The sampler is case-driven rather than uniform: each scene is assembled from
named case templates so that the edges the duty of caution lives on are
guaranteed to appear in the corpus rather than appearing by luck.

    python finetune/scene_factory.py --n 200 --out data/scenes.jsonl
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import analysis  # noqa: E402
from surface_vocab import load_vocab  # noqa: E402

GEARS = ["bottom_trawl", "purse_seine", "gillnet", "longline", "dredge"]

# Each case is (name, weight). The weights are deliberately flat-ish: this is a
# stress corpus, not a sample of reality. Reality is mostly boring records and
# a corpus that mirrored it would teach the model almost nothing about the
# cases where the system is allowed to be wrong in only one direction.
CASES = [
    ("dark_large_in_reserve", 3),      # the textbook high-priority candidate
    ("dark_large_in_mpa", 3),
    ("dark_large_open_water", 3),
    ("dark_small_in_reserve", 3),      # AIS suppressed, zone indicator survives
    ("dark_small_open_water", 2),      # AIS suppressed, nothing left: no brief
    ("near_threshold_dark", 3),        # inconclusive band, the hardest case
    ("exactly_threshold_dark", 1),     # 15.0 m is NOT covered. Strictly.
    ("matched_gear_in_closure", 3),    # identified and still an indicator
    ("matched_in_zone_clean", 2),      # in a zone, no indicator: must not brief
    ("matched_open_water", 2),
    ("fixed_structure", 2),            # false-positive guard
]


def _rect(lat0: float, lon0: float, dlat0: float, dlat1: float,
          dlon0: float, dlon1: float) -> list:
    return [[round(lat0 + dlat0, 4), round(lon0 + dlon0, 4)],
            [round(lat0 + dlat0, 4), round(lon0 + dlon1, 4)],
            [round(lat0 + dlat1, 4), round(lon0 + dlon1, 4)],
            [round(lat0 + dlat1, 4), round(lon0 + dlon0, 4)]]


def _inside(rng: random.Random, poly: list) -> tuple:
    lats = [p[0] for p in poly]
    lons = [p[1] for p in poly]
    # 10% inset so a rounded coordinate never lands outside its own zone.
    ilat = (max(lats) - min(lats)) * 0.1
    ilon = (max(lons) - min(lons)) * 0.1
    return (round(rng.uniform(min(lats) + ilat, max(lats) - ilat), 4),
            round(rng.uniform(min(lons) + ilon, max(lons) - ilon), 4))


def _outside(rng: random.Random, lat0: float, lon0: float, zones: list) -> tuple:
    for _ in range(200):
        lat = round(rng.uniform(lat0 - 0.25, lat0 + 0.95), 4)
        lon = round(rng.uniform(lon0 - 0.95, lon0 + 0.05), 4)
        if not any(_point_in(lat, lon, z["polygon"]) for z in zones):
            return lat, lon
    return round(lat0 - 0.24, 4), round(lon0 + 0.04, 4)


def _point_in(lat: float, lon: float, poly: list) -> bool:
    lats = [p[0] for p in poly]
    lons = [p[1] for p in poly]
    return min(lats) <= lat <= max(lats) and min(lons) <= lon <= max(lons)


def build_regulatory_layer(rng: random.Random, vocab: dict, scene_day: date) -> dict:
    """A three-zone regulatory layer with randomised geography and naming."""
    lat0 = round(rng.uniform(35.5, 43.0), 3)
    lon0 = round(rng.uniform(-9.0, 3.0), 3)

    mpa_poly = _rect(lat0, lon0, 0.20, 0.45, -0.70, -0.40)
    cls_poly = _rect(lat0, lon0, 0.50, 0.75, -0.60, -0.25)
    res_poly = _rect(lat0, lon0, 0.00, 0.15, -0.35, -0.15)

    # The closure is active in roughly two scenes out of three. An inactive
    # closure is not a throwaway: it is the case where the model must NOT cite
    # the closure, and the validator checks exactly that.
    if rng.random() < 0.66:
        c_start = scene_day - timedelta(days=rng.randint(5, 60))
        c_end = scene_day + timedelta(days=rng.randint(5, 60))
    else:
        c_start = scene_day + timedelta(days=rng.randint(30, 120))
        c_end = c_start + timedelta(days=rng.randint(30, 90))

    mpa_gear = rng.sample(GEARS, rng.randint(1, 3))
    cls_gear = rng.sample(GEARS, rng.randint(1, 2))

    zones = [
        {"id": "MPA-01", "name": vocab["mpa_name"],
         "type": "marine_protected_area",
         "designation": "Natura 2000 marine (synthetic)",
         "prohibited_gear": mpa_gear, "closure": None, "polygon": mpa_poly},
        {"id": "CLS-02", "name": vocab["closure_name"],
         "type": "seasonal_closure",
         "designation": "Seasonal closure (synthetic)",
         "prohibited_gear": cls_gear,
         "closure": {"start": c_start.isoformat(), "end": c_end.isoformat(),
                     "reason": vocab["closure_reason"]},
         "polygon": cls_poly},
        {"id": "RES-03", "name": vocab["reserve_name"],
         "type": "integral_reserve",
         "designation": "Marine reserve of fishing interest (synthetic)",
         "prohibited_gear": ["all"], "closure": None, "polygon": res_poly},
    ]

    fix_lat = round((mpa_poly[0][0] + mpa_poly[2][0]) / 2, 4)
    fix_lon = round((mpa_poly[0][1] + mpa_poly[1][1]) / 2, 4)

    config = {
        "ais_length_threshold_m": 15.0,
        "ais_legal_basis": ("Article 10(1), Council Regulation (EC) No 1224/2009, "
                            "as amended by Regulation (EU) 2023/2842"),
        "lawful_dark_derogation": (
            "Article 10(2), Council Regulation (EC) No 1224/2009, as amended by "
            "Regulation (EU) 2023/2842: the master of a Union fishing vessel may "
            "switch off the AIS in exceptional circumstances where the safety or "
            "security of the crew is imminently at risk, and must notify the "
            "switch-off and its reason to the competent authorities."),
        "length_sigma_m": 2.0,
        "length_sigma_k": 1.0,
        "vms_length_threshold_m": 12.0,
        "fishing_score_threshold": 0.7,
        "score_weights": {"ais_dark": 40, "ais_dark_inconclusive": 20,
                          "zone_violation": 30, "fishing_context": 10},
        "patrol_base": {"lat": round(lat0 + 0.13, 4),
                        "lon": round(lon0 + 0.21, 4),
                        "name": vocab["patrol_base_name"]},
        "patrol_radius_km": rng.choice([90, 120, 150, 180]),
        "study_area": vocab["study_area"],
        "output_language": vocab["output_language"],
        "environment": {"season": {"start": "10-10", "end": "03-31"},
                        "dark_illumination": 0.25},
    }

    return {
        "_note": "SYNTHETIC. Generated by finetune/scene_factory.py.",
        "config": config,
        "zones": zones,
        "fixed_structures": [
            {"id": "FIX-01", "name": vocab["structure_name"],
             "type": rng.choice(["fixed_platform", "wind_turbine",
                                 "aquaculture_cage", "navigation_buoy"]),
             "lat": fix_lat, "lon": fix_lon, "match_radius_m": 400},
        ],
        "_origin": [lat0, lon0],
    }


def build_detection(rng: random.Random, case: str, idx: int,
                    zones_doc: dict) -> dict:
    zones = {z["id"]: z for z in zones_doc["zones"]}
    lat0, lon0 = zones_doc["_origin"]
    fix = zones_doc["fixed_structures"][0]

    def gear_for(zone_id, prohibited: bool):
        banned = zones[zone_id]["prohibited_gear"]
        if banned == ["all"]:
            return rng.choice(GEARS)
        pool = banned if prohibited else [g for g in GEARS if g not in banned]
        return rng.choice(pool or GEARS)

    d = {"id": f"D-{idx:03d}", "heading": rng.randint(0, 359)}

    if case == "dark_large_in_reserve":
        d["lat"], d["lon"] = _inside(rng, zones["RES-03"]["polygon"])
        d.update(estimated_length_m=round(rng.uniform(18.0, 42.0), 1),
                 ais_matched=False, fishing_score=round(rng.uniform(0.72, 0.98), 2),
                 speed_kn=round(rng.uniform(1.5, 4.5), 1),
                 likely_gear=gear_for("RES-03", True))

    elif case == "dark_large_in_mpa":
        d["lat"], d["lon"] = _inside(rng, zones["MPA-01"]["polygon"])
        d.update(estimated_length_m=round(rng.uniform(18.0, 45.0), 1),
                 ais_matched=False, fishing_score=round(rng.uniform(0.60, 0.97), 2),
                 speed_kn=round(rng.uniform(1.5, 5.0), 1),
                 likely_gear=gear_for("MPA-01", rng.random() < 0.7))

    elif case == "dark_large_open_water":
        d["lat"], d["lon"] = _outside(rng, lat0, lon0, zones_doc["zones"])
        d.update(estimated_length_m=round(rng.uniform(18.0, 50.0), 1),
                 ais_matched=False, fishing_score=round(rng.uniform(0.30, 0.95), 2),
                 speed_kn=round(rng.uniform(2.0, 9.0), 1),
                 likely_gear=rng.choice(GEARS))

    elif case == "dark_small_in_reserve":
        d["lat"], d["lon"] = _inside(rng, zones["RES-03"]["polygon"])
        d.update(estimated_length_m=round(rng.uniform(5.5, 12.4), 1),
                 ais_matched=False, fishing_score=round(rng.uniform(0.74, 0.97), 2),
                 speed_kn=round(rng.uniform(1.2, 3.5), 1),
                 likely_gear=rng.choice(["gillnet", "longline", "purse_seine"]))

    elif case == "dark_small_open_water":
        d["lat"], d["lon"] = _outside(rng, lat0, lon0, zones_doc["zones"])
        d.update(estimated_length_m=round(rng.uniform(5.0, 12.0), 1),
                 ais_matched=False, fishing_score=round(rng.uniform(0.20, 0.95), 2),
                 speed_kn=round(rng.uniform(1.0, 7.0), 1),
                 likely_gear=rng.choice(GEARS))

    elif case == "near_threshold_dark":
        # The band where the engine says "inconclusive" and the brief has to
        # stay conditional. length_sigma_m = 2.0, k = 1.0.
        d["lat"], d["lon"] = (_inside(rng, zones["MPA-01"]["polygon"])
                              if rng.random() < 0.5
                              else _outside(rng, lat0, lon0, zones_doc["zones"]))
        d.update(estimated_length_m=round(rng.uniform(13.1, 16.9), 1),
                 ais_matched=False, fishing_score=round(rng.uniform(0.40, 0.96), 2),
                 speed_kn=round(rng.uniform(1.5, 6.0), 1),
                 likely_gear=rng.choice(GEARS))

    elif case == "exactly_threshold_dark":
        d["lat"], d["lon"] = _outside(rng, lat0, lon0, zones_doc["zones"])
        d.update(estimated_length_m=15.0, ais_matched=False,
                 fishing_score=round(rng.uniform(0.50, 0.95), 2),
                 speed_kn=round(rng.uniform(1.5, 6.0), 1),
                 likely_gear=rng.choice(GEARS))

    elif case == "matched_gear_in_closure":
        d["lat"], d["lon"] = _inside(rng, zones["CLS-02"]["polygon"])
        d.update(estimated_length_m=round(rng.uniform(16.0, 48.0), 1),
                 ais_matched=True, fishing_score=round(rng.uniform(0.72, 0.98), 2),
                 speed_kn=round(rng.uniform(1.5, 4.0), 1),
                 likely_gear=gear_for("CLS-02", True),
                 mmsi=str(rng.randint(200000000, 299999999)),
                 name=rng.choice(["VESSEL ALFA", "VESSEL BRAVO", "VESSEL CHARLIE",
                                  "VESSEL DELTA", "VESSEL ECHO"]),
                 flag=rng.choice(["ESP", "PRT", "FRA", "ITA"]))

    elif case == "matched_in_zone_clean":
        zid = rng.choice(["MPA-01", "CLS-02"])
        d["lat"], d["lon"] = _inside(rng, zones[zid]["polygon"])
        d.update(estimated_length_m=round(rng.uniform(16.0, 40.0), 1),
                 ais_matched=True, fishing_score=round(rng.uniform(0.05, 0.45), 2),
                 speed_kn=round(rng.uniform(7.0, 12.0), 1),
                 likely_gear=gear_for(zid, False),
                 mmsi=str(rng.randint(200000000, 299999999)),
                 name=rng.choice(["VESSEL FOXTROT", "VESSEL GOLF", "VESSEL HOTEL"]),
                 flag=rng.choice(["ESP", "PRT", "FRA"]))

    elif case == "matched_open_water":
        d["lat"], d["lon"] = _outside(rng, lat0, lon0, zones_doc["zones"])
        d.update(estimated_length_m=round(rng.uniform(14.0, 55.0), 1),
                 ais_matched=True, fishing_score=round(rng.uniform(0.05, 0.9), 2),
                 speed_kn=round(rng.uniform(2.0, 11.0), 1),
                 likely_gear=rng.choice(GEARS),
                 mmsi=str(rng.randint(200000000, 299999999)),
                 name=rng.choice(["VESSEL INDIA", "VESSEL JULIET", "VESSEL KILO"]),
                 flag=rng.choice(["ESP", "PRT", "MAR"]))

    elif case == "fixed_structure":
        jitter = rng.uniform(-0.001, 0.001)
        d.update(lat=round(fix["lat"] + jitter, 4),
                 lon=round(fix["lon"] + jitter, 4),
                 estimated_length_m=round(rng.uniform(20.0, 60.0), 1),
                 ais_matched=False, fishing_score=round(rng.uniform(0.5, 0.95), 2),
                 speed_kn=0.0, likely_gear=rng.choice(GEARS))
    else:
        raise ValueError(f"unknown case {case}")

    return d


def build_scene(seed: int, vocab_pool: list) -> dict:
    rng = random.Random(seed)
    vocab = vocab_pool[seed % len(vocab_pool)]

    scene_day = date(2026, 1, 1) + timedelta(days=rng.randint(0, 364))
    zones_doc = build_regulatory_layer(rng, vocab, scene_day)

    names = [c for c, _ in CASES]
    weights = [w for _, w in CASES]
    n = rng.randint(7, 16)
    chosen = rng.choices(names, weights=weights, k=n)
    # Guarantee at least one candidate and at least one record that must not be
    # briefed, so every scene exercises both directions of the duty of caution.
    chosen[0] = rng.choice(["dark_large_in_reserve", "dark_large_in_mpa",
                            "matched_gear_in_closure"])
    chosen[1] = rng.choice(["matched_in_zone_clean", "dark_small_open_water",
                            "fixed_structure"])
    rng.shuffle(chosen)

    detections = [build_detection(rng, case, i + 1, zones_doc)
                  for i, case in enumerate(chosen)]

    detections_doc = {
        "_note": "SYNTHETIC. Generated by finetune/scene_factory.py.",
        "scene": {"source": "Sentinel-1 (synthetic)", "mode": "IW / VV-VH",
                  "timestamp": f"{scene_day.isoformat()}T"
                               f"{rng.randint(0, 23):02d}:{rng.randint(0, 59):02d}:00Z",
                  "area": vocab["study_area"]},
        "detections": detections,
    }

    zones_doc.pop("_origin")
    return {"seed": seed, "cases": chosen,
            "zones_doc": zones_doc, "detections_doc": detections_doc}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default="data/scenes.jsonl")
    ap.add_argument("--vocab", default="data/surface_vocab.jsonl",
                    help="output of surface_vocab.py; falls back to the "
                         "built-in static pool if absent")
    args = ap.parse_args()

    vocab_pool = load_vocab(args.vocab)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    kept = 0
    coverage: dict = {}
    with out.open("w", encoding="utf-8") as fh:
        for i in range(args.n):
            scene = build_scene(args.seed + i, vocab_pool)
            # A scene the engine cannot turn into at least one candidate has
            # nothing for a writer to learn from. Drop it rather than teach the
            # model to produce an empty report.
            dossier = analysis.analyse(scene["zones_doc"], scene["detections_doc"])
            if not dossier["inspection_candidates"]:
                continue
            for case in scene["cases"]:
                coverage[case] = coverage.get(case, 0) + 1
            fh.write(json.dumps(scene, ensure_ascii=False) + "\n")
            kept += 1

    print(f"{kept}/{args.n} scenes written to {out}")
    print("case coverage:")
    for case, count in sorted(coverage.items(), key=lambda kv: -kv[1]):
        print(f"  {case:<26} {count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
