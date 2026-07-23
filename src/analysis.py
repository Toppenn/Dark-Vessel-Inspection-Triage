"""Deterministic cross-reference engine.

This is NOT the LLM. This is the tool the agents call: pure, reproducible,
auditable computation. In an enforcement file, positions, geometry and scores
cannot come out of a generative model.

DUTY OF CAUTION (deliberate and explicit):
A vessel that is not broadcasting AIS is NOT automatically an offender.
Fishing vessels at or below the legal length threshold are not required to
broadcast at all. For those vessels the AIS indicator and its score
contribution are suppressed — and ONLY those. Every other indicator (gear
prohibited in a zone, fishing during an active closure) is assessed exactly as
for any other vessel: a small dark vessel trawling inside an integral reserve
is still an inspection candidate on the strength of its zone indicators alone.
Suppressing the vessel instead of the indicator would be the opposite failure:
under-reporting.

SCORING INVARIANT: score > 0 if and only if potential_indicators is non-empty.
Presence inside a regulated zone does not score by itself; only a concrete
violation (prohibited gear, fishing during an active closure, or the AIS
carriage requirement potentially engaged) generates both an indicator and
points. The score is an internal ordering aid: it is presented ordinally
(high/medium), never as a headline number.

ERROR POLICY: critical inputs that are missing or malformed raise. A silent
default here (a length of 0.0, today's date, an ignored closure) can activate
or deactivate a legal threshold or a seasonal closure without anyone noticing.
"""

from datetime import date, datetime

import geo

# AIS applicability of the carriage requirement given the radar length
# estimate. The estimate carries sensor uncertainty and the legal threshold
# sits near the detection floor, so applicability is three-state.
AIS_APPLICABLE = "applicable"
AIS_INCONCLUSIVE = "near_threshold_inconclusive"
AIS_NOT_APPLICABLE = "not_applicable"

DEFAULT_WEIGHTS = {
    "ais_dark": 40,
    "ais_dark_inconclusive": 20,
    "zone_violation": 30,
    "fishing_context": 10,
}

HIGH_THRESHOLD = 70
MEDIUM_THRESHOLD = 40

CANDIDATE_CLASSES = ("high_priority", "medium_priority")


def _scene_date(scene: dict) -> date:
    timestamp = scene.get("timestamp")
    try:
        return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).date()
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError(
            f"scene timestamp is missing or invalid: {timestamp!r}. A silently "
            f"wrong analysis date can activate or deactivate seasonal closures."
        ) from exc


def _closure_active(zone: dict, day: date) -> bool:
    closure = zone.get("closure")
    if not closure:
        return False
    try:
        start = date.fromisoformat(closure["start"])
        end = date.fromisoformat(closure["end"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            f"zone {zone.get('id')!r}: malformed closure {closure!r}. A closure "
            f"silently treated as inactive would hide violations."
        ) from exc
    return start <= day <= end


def _length(detection: dict) -> float:
    length = detection.get("estimated_length_m")
    if isinstance(length, bool) or not isinstance(length, (int, float)):
        raise ValueError(
            f"detection {detection.get('id')!r}: estimated_length_m is missing "
            f"or not numeric ({length!r}). Defaulting to 0.0 would silently "
            f"place the vessel below the AIS carriage threshold.")
    return float(length)


def _ais_status(detection: dict) -> str:
    """matched / dark / unknown. An absent field is NOT evidence of darkness."""
    if "ais_matched" not in detection:
        return "unknown"
    return "matched" if detection["ais_matched"] else "dark"


def _ais_applicability(length: float, threshold: float,
                       sigma: float, k: float) -> str:
    # "Exceeding" the threshold is strict: exactly 15.0 m is not covered.
    if length - k * sigma > threshold:
        return AIS_APPLICABLE
    if length + k * sigma > threshold:
        return AIS_INCONCLUSIVE
    return AIS_NOT_APPLICABLE


def _zones_containing(detection: dict, zones: list) -> list:
    return [z for z in zones
            if geo.point_in_polygon(detection["lat"], detection["lon"], z["polygon"])]


def assess_detection(detection: dict, zones: list, config: dict, day: date) -> dict:
    """Assess a single detection and return its record with an itemised score."""
    length_threshold = config["ais_length_threshold_m"]
    fishing_threshold = config["fishing_score_threshold"]
    sigma = config.get("length_sigma_m", 0.0)
    sigma_k = config.get("length_sigma_k", 1.0)
    vms_threshold = config.get("vms_length_threshold_m", 12.0)
    weights = {**DEFAULT_WEIGHTS, **config.get("score_weights", {})}
    ais_legal_basis = config.get(
        "ais_legal_basis", "the AIS carriage and operation requirement")

    length = _length(detection)
    ais_status = _ais_status(detection)
    matched = ais_status == "matched"
    dark = ais_status == "dark"
    fishing = detection.get("fishing_score", 0.0) >= fishing_threshold
    gear = detection.get("likely_gear", "unknown")
    applicability = _ais_applicability(length, length_threshold, sigma, sigma_k)

    containing = _zones_containing(detection, zones)
    indicators = []
    context = []
    score_items = []
    ais_suppressed = False

    # --- AIS indicator: dark vessels only, and only above the threshold.
    # The carriage requirement binds UNION fishing vessels exceeding the
    # threshold; a dark vessel's flag state is unknown by definition, so the
    # indicator is phrased conditionally.
    if dark and applicability == AIS_APPLICABLE:
        indicators.append({
            "kind": "ais", "zone": None, "zone_id": None,
            "reason": (
                f"radar-estimated length {length} m is above the "
                f"{length_threshold} m threshold beyond sensor uncertainty and "
                f"no AIS broadcast was matched; if this is a Union fishing "
                f"vessel exceeding {length_threshold} m LOA, the AIS carriage "
                f"and operation requirement is potentially concerned "
                f"({ais_legal_basis})"),
        })
        score_items.append((
            "no AIS broadcast matched while the carriage requirement is "
            "potentially engaged (length firmly above threshold)",
            weights["ais_dark"]))
    elif dark and applicability == AIS_INCONCLUSIVE:
        indicators.append({
            "kind": "ais_inconclusive", "zone": None, "zone_id": None,
            "reason": (
                f"radar-estimated length {length} m is near the "
                f"{length_threshold} m threshold (within k*sigma = "
                f"{sigma_k}*{sigma} m sensor uncertainty): length near threshold, "
                f"inconclusive; if this is a Union fishing vessel exceeding "
                f"{length_threshold} m LOA, the AIS carriage and operation "
                f"requirement may be concerned ({ais_legal_basis})"),
        })
        score_items.append((
            "no AIS broadcast matched; length near threshold, inconclusive "
            "(degraded indicator)", weights["ais_dark_inconclusive"]))
    elif dark:
        # Below the carriage threshold: suppress the AIS indicator and its
        # score contribution — and nothing else.
        ais_suppressed = True
    elif ais_status == "unknown":
        context.append(
            "AIS matching status is unknown for this detection: absence of a "
            "match cannot be asserted, so no AIS indicator is raised")

    # --- Zone indicators: only concrete violations score, never presence.
    for zone in containing:
        prohibited = zone.get("prohibited_gear", [])
        if "all" in prohibited:
            # Gear identity is irrelevant where all fishing gear is prohibited;
            # the violation is apparent fishing activity. Transit is not fishing.
            if fishing or (matched and gear not in ("in_transit", "unknown")):
                indicators.append({
                    "kind": "zone", "zone": zone["name"], "zone_id": zone["id"],
                    "reason": (
                        f"apparent fishing activity inside {zone['type']} "
                        f"'{zone['name']}' where all fishing gear is prohibited "
                        f"(activity per contextual classifier, non-observational)"),
                })
                score_items.append((
                    f"apparent fishing where all gear is prohibited "
                    f"({zone['id']})", weights["zone_violation"]))
        elif gear in prohibited:
            if matched:
                # For an AIS-matched vessel the gear class comes from the fleet
                # registry, not from radar inference.
                indicators.append({
                    "kind": "zone", "zone": zone["name"], "zone_id": zone["id"],
                    "reason": (f"gear '{gear}' (fleet registry) prohibited in "
                               f"{zone['type']} '{zone['name']}'"),
                })
                score_items.append((
                    f"registry gear prohibited in zone ({zone['id']})",
                    weights["zone_violation"]))
            else:
                # For an unmatched detection the gear class is enrichment, not
                # observation: context only, never an indicator.
                context.append(
                    f"radar-inferred gear class '{gear}' would be prohibited in "
                    f"{zone['type']} '{zone['name']}', but gear inference for an "
                    f"unmatched detection is enrichment, not observation - "
                    f"context only, to be verified on inspection")
        if _closure_active(zone, day) and fishing:
            indicators.append({
                "kind": "zone", "zone": zone["name"], "zone_id": zone["id"],
                "reason": (
                    f"contextual classifier indicates likely fishing activity "
                    f"(non-observational) during active closure "
                    f"({zone['closure']['reason']}) in '{zone['name']}'"),
            })
            score_items.append((
                f"likely fishing during active closure ({zone['id']})",
                weights["zone_violation"]))

    # Corroboration only: the fishing classifier is contextual and never
    # scores on its own — the invariant score>0 ⟺ indicators holds.
    if fishing and indicators:
        score_items.append((
            "contextual classifier indicates likely fishing activity "
            "(non-observational) - corroboration only",
            weights["fishing_context"]))

    total = sum(points for _, points in score_items)

    ais_note = None
    if ais_suppressed:
        ais_note = ("Below the AIS carriage threshold: absence of an AIS "
                    "broadcast is not an indicator. Other indicators, if any, "
                    "remain.")
        if length >= vms_threshold:
            ais_note += (
                f" The appropriate cross-check is VMS: vessels of "
                f"{vms_threshold} m and over must carry an operational VMS "
                f"(since January 2026), and the authority already holds that "
                f"track.")

    if total >= HIGH_THRESHOLD:
        classification = "high_priority"
        note = f"{len(indicators)} independent indicators concur."
    elif total >= MEDIUM_THRESHOLD:
        classification = "medium_priority"
        note = (f"{len(indicators)} indicator(s); partial, requires "
                f"corroboration.")
    elif total > 0:
        classification = "low_priority"
        note = ("Isolated or degraded indicator below the candidate "
                "threshold; not an inspection candidate.")
    elif ais_suppressed:
        classification = "ais_not_applicable"
        note = ais_note
    else:
        classification = "no_indicators"
        note = "Nothing that would justify an inspection."

    record = {
        "id": detection["id"],
        "position": {"lat": detection["lat"], "lon": detection["lon"]},
        "estimated_length_m": length,
        "ais": {"matched": "matched", "dark": "unmatched (dark)",
                "unknown": "unknown"}[ais_status],
        "ais_status": ais_status,
        "ais_applicability": applicability,
        "ais_indicator_suppressed": ais_suppressed,
        "jurisdiction": detection.get("flag", "unknown") if matched else "unknown",
        "fishing_score": detection.get("fishing_score"),
        "speed_kn": detection.get("speed_kn"),
        "likely_gear": gear,
        "zones": [{"id": z["id"], "name": z["name"], "type": z["type"]}
                  for z in containing],
        "potential_indicators": indicators,
        "contextual_notes": context,
        "score": total,
        "score_breakdown": [{"factor": f, "points": p} for f, p in score_items],
        "classification": classification,
        "note": note,
    }
    if ais_note:
        record["ais_note"] = ais_note
    if matched:
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
             "no_indicators": 3, "ais_not_applicable": 4}
    records.sort(key=lambda r: (order[r["classification"]], -r["score"]))

    summary = {}
    for record in records:
        summary[record["classification"]] = summary.get(record["classification"], 0) + 1

    active_closures = [{"zone": z["name"], "reason": z["closure"]["reason"]}
                       for z in zones if _closure_active(z, day)]

    candidates = [r for r in records if r["classification"] in CANDIDATE_CLASSES]

    # --- Patrol sequence: turn the ranking into a triage tool.
    patrol_base = config.get("patrol_base")
    patrol_radius = config.get("patrol_radius_km")
    patrol_sequence = []
    if patrol_base:
        for record in records:
            record["distance_from_base_km"] = geo.distance_km(
                patrol_base["lat"], patrol_base["lon"],
                record["position"]["lat"], record["position"]["lon"])
        in_range = [r for r in candidates
                    if patrol_radius is None
                    or r["distance_from_base_km"] <= patrol_radius]
        in_range.sort(key=lambda r: (order[r["classification"]],
                                     r["distance_from_base_km"]))
        patrol_sequence = [{
            "id": r["id"],
            "priority": r["classification"],
            "distance_from_base_km": r["distance_from_base_km"],
            "position": r["position"],
        } for r in in_range]

    return {
        "scene": scene,
        "analysis_date": day.isoformat(),
        "study_area": config.get("study_area"),
        "output_language": config.get("output_language", "English"),
        "ais_length_threshold_m": config["ais_length_threshold_m"],
        "length_sigma_m": config.get("length_sigma_m", 0.0),
        "vms_length_threshold_m": config.get("vms_length_threshold_m"),
        "ais_legal_basis": config.get("ais_legal_basis"),
        "lawful_dark_derogation": config.get("lawful_dark_derogation"),
        "scoring_note": ("Weights are transparent but not yet calibrated against "
                         "enforcement outcomes. They order candidates; they are not "
                         "probabilities of infringement. Points are awarded only "
                         "for concrete indicators, and priority is expressed "
                         "ordinally (high/medium), never as a headline number."),
        "regulated_zones": [
            {"id": z["id"], "name": z["name"], "type": z["type"],
             "prohibited_gear": z["prohibited_gear"],
             "closure_active": _closure_active(z, day)}
            for z in zones
        ],
        "active_closures": active_closures,
        "patrol_base": patrol_base,
        "patrol_radius_km": patrol_radius,
        "patrol_sequence": patrol_sequence,
        "total_detections": len(records),
        "classification_summary": summary,
        "records": records,
        "inspection_candidates": candidates,
        "ais_indicator_suppressed": [r for r in records
                                     if r["ais_indicator_suppressed"]],
    }
