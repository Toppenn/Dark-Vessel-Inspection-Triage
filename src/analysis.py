"""Deterministic cross-reference engine.

This is NOT the LLM. This is the tool the agents call: pure, reproducible,
auditable computation. In an enforcement file, positions, geometry and scores
cannot come out of a generative model.

DUTY OF CAUTION (deliberate and explicit):
A vessel that is not broadcasting AIS is NOT automatically an offender.
Fishing vessels below the legal length threshold are not required to broadcast
at all. The system marks those as NON-ASSESSABLE, scores them zero and never
prioritises them. This is not a technical detail — it is what separates a
legitimate triage tool from a machine that accuses people without basis.
"""

from datetime import date, datetime

import geo


def _scene_date(scene: dict) -> date:
    timestamp = scene.get("timestamp", "")
    try:
        return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).date()
    except ValueError:
        return date.today()


def _closure_active(zone: dict, day: date) -> bool:
    closure = zone.get("closure")
    if not closure:
        return False
    try:
        start = date.fromisoformat(closure["start"])
        end = date.fromisoformat(closure["end"])
    except (KeyError, ValueError):
        return False
    return start <= day <= end


def _gear_prohibited(zone: dict, gear: str) -> bool:
    prohibited = zone.get("prohibited_gear", [])
    return "all" in prohibited or gear in prohibited


def _zones_containing(detection: dict, zones: list) -> list:
    return [z for z in zones
            if geo.point_in_polygon(detection["lat"], detection["lon"], z["polygon"])]


def assess_detection(detection: dict, zones: list, config: dict, day: date) -> dict:
    """Assess a single detection and return its record with an itemised score."""
    length_threshold = config["ais_length_threshold_m"]
    fishing_threshold = config["fishing_score_threshold"]

    length = detection.get("estimated_length_m", 0.0)
    dark = not detection.get("ais_matched", False)
    ais_required = length >= length_threshold
    fishing = detection.get("fishing_score", 0.0) >= fishing_threshold
    gear = detection.get("likely_gear", "unknown")

    containing = _zones_containing(detection, zones)
    indicators = []
    for zone in containing:
        if _gear_prohibited(zone, gear):
            indicators.append({
                "zone": zone["name"], "zone_id": zone["id"],
                "reason": f"gear '{gear}' prohibited in {zone['type']}",
            })
        if _closure_active(zone, day) and fishing:
            indicators.append({
                "zone": zone["name"], "zone_id": zone["id"],
                "reason": f"fishing activity during closure ({zone['closure']['reason']})",
            })

    # --- Itemised, traceable score ---
    score_items = []
    if dark and ais_required:
        score_items.append(("not broadcasting AIS while required to by length", 40))
    if containing:
        score_items.append((f"inside regulated zone ({containing[0]['type']})", 25))
    if fishing:
        score_items.append(("movement consistent with active fishing", 20))
    if indicators:
        score_items.append(("prohibited gear or active closure in that zone", 15))

    total = sum(points for _, points in score_items)

    # --- Classification, with the duty of caution applied first ---
    if dark and not ais_required:
        classification = "non_assessable"
        total = 0
        note = (f"Estimated length {length} m is below the AIS carriage threshold "
                f"({length_threshold} m). Not broadcasting is not an indicator here. "
                f"Excluded from prioritisation.")
    elif total >= 70:
        classification = "high_priority"
        note = "Several independent indicators coincide."
    elif total >= 40:
        classification = "medium_priority"
        note = "Partial indicators; requires corroboration."
    elif total > 0:
        classification = "low_priority"
        note = "Isolated indicator."
    else:
        classification = "no_indicators"
        note = "Nothing that would justify an inspection."

    record = {
        "id": detection["id"],
        "position": {"lat": detection["lat"], "lon": detection["lon"]},
        "estimated_length_m": length,
        "ais": "unmatched (dark)" if dark else "matched",
        "ais_required": ais_required,
        "fishing_score": detection.get("fishing_score"),
        "speed_kn": detection.get("speed_kn"),
        "likely_gear": gear,
        "zones": [{"id": z["id"], "name": z["name"], "type": z["type"]}
                  for z in containing],
        "potential_indicators": indicators,
        "score": total,
        "score_breakdown": [{"factor": f, "points": p} for f, p in score_items],
        "classification": classification,
        "note": note,
    }
    if not dark:
        record["identity"] = {
            "mmsi": detection.get("mmsi"),
            "name": detection.get("vessel_name"),
            "flag": detection.get("flag"),
        }
    return record


def analyse(zones_doc: dict, detections_doc: dict) -> dict:
    """Full cross-reference. Returns the factual dossier consumed by the agents."""
    config = zones_doc["config"]
    zones = zones_doc["zones"]
    scene = detections_doc["scene"]
    day = _scene_date(scene)

    records = [assess_detection(d, zones, config, day)
               for d in detections_doc["detections"]]

    order = {"high_priority": 0, "medium_priority": 1, "low_priority": 2,
             "no_indicators": 3, "non_assessable": 4}
    records.sort(key=lambda r: (order[r["classification"]], -r["score"]))

    summary = {}
    for record in records:
        summary[record["classification"]] = summary.get(record["classification"], 0) + 1

    active_closures = [{"zone": z["name"], "reason": z["closure"]["reason"]}
                       for z in zones if _closure_active(z, day)]

    return {
        "scene": scene,
        "analysis_date": day.isoformat(),
        "study_area": config.get("study_area"),
        "output_language": config.get("output_language", "English"),
        "ais_length_threshold_m": config["ais_length_threshold_m"],
        "regulated_zones": [
            {"id": z["id"], "name": z["name"], "type": z["type"],
             "prohibited_gear": z["prohibited_gear"],
             "closure_active": _closure_active(z, day)}
            for z in zones
        ],
        "active_closures": active_closures,
        "total_detections": len(records),
        "classification_summary": summary,
        "records": records,
        "inspection_candidates": [r for r in records
                                  if r["classification"].endswith("_priority")],
        "excluded_by_caution": [r for r in records
                                if r["classification"] == "non_assessable"],
    }
