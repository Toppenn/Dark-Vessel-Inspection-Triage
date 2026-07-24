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

import environment
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

# Two or more independent indicators concurring makes a record high priority;
# a single indicator is worth an inspector's attention but not precedence.
HIGH_INDICATOR_COUNT = 2

CANDIDATE_CLASSES = ("high_priority", "medium_priority")


def _scene_date(scene: dict) -> date:
    timestamp = scene.get("timestamp")
    if not isinstance(timestamp, str):
        raise ValueError(
            f"scene timestamp is missing or not a string: {timestamp!r}. A "
            f"silently wrong analysis date can activate or deactivate seasonal "
            f"closures.")
    try:
        return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).date()
    except ValueError as exc:
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


# Default match radius for a charted fixed structure when it declares none.
# A platform's safety zone is ~500 m; a lone turbine or buoy is tighter. 300 m
# is a conservative middle that a structure can override per entry.
DEFAULT_FIXED_MATCH_M = 300.0


def _fixed_structure_match(detection: dict, structures: list) -> dict:
    """Return the nearest charted fixed structure the detection falls on, or None.

    Platforms, wind turbines, buoys and aquaculture cages are bright, stationary
    radar returns that a CFAR detector (or GFW's SAR feed) reads as vessels. A
    blob sitting on a charted structure is most parsimoniously that structure.
    """
    best = None
    best_km = None
    for s in structures:
        radius_km = s.get("match_radius_m", DEFAULT_FIXED_MATCH_M) / 1000.0
        d_km = geo.distance_km(detection["lat"], detection["lon"], s["lat"], s["lon"])
        if d_km <= radius_km and (best_km is None or d_km < best_km):
            best, best_km = s, d_km
    return best


def assess_detection(detection: dict, zones: list, config: dict, day: date,
                     structures: list = None) -> dict:
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
    # A missing activity score must not silently mean "not fishing": that would
    # suppress zone indicators without anyone noticing. Length, timestamp and
    # closure already fail loudly; this field decides indicators too.
    if "fishing_score" not in detection:
        raise ValueError(
            f"detection {detection.get('id', '?')} has no fishing_score; a "
            f"missing activity score cannot be read as absence of activity")
    fishing = detection["fishing_score"] >= fishing_threshold
    # Gear may legitimately be absent — it is context for unmatched detections
    # and only becomes an indicator for AIS-matched ones, where it comes from
    # the fleet registry. "unknown" never produces an indicator.
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
            # Degraded: it may support a candidacy raised by something else, but
            # it must not create one on its own. The length estimate that
            # produced it does not clear the threshold once its own uncertainty
            # is taken into account.
            "degraded": True,
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
            # Presence is not activity. The registry gear class says what a
            # vessel is licensed for, not what it is doing, so it cannot support
            # a claim of "apparent fishing activity". Only the activity
            # classifier can, and it must clear its own threshold.
            if fishing:
                indicators.append({
                    "kind": "zone", "zone": zone["name"], "zone_id": zone["id"],
                    "rests_on_activity": True,
                    "reason": (
                        f"apparent fishing activity inside {zone['type']} "
                        f"'{zone['name']}' ({zone['id']}) where all fishing gear "
                        f"is prohibited "
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
                               f"{zone['type']} '{zone['name']}' ({zone['id']})"),
                })
                score_items.append((
                    f"registry gear prohibited in zone ({zone['id']})",
                    weights["zone_violation"]))
            else:
                # For an unmatched detection the gear class is enrichment, not
                # observation: context only, never an indicator.
                context.append(
                    f"radar-inferred gear class '{gear}' would be prohibited in "
                    f"{zone['type']} '{zone['name']}' ({zone['id']}), but gear "
                    f"inference for an "
                    f"unmatched detection is enrichment, not observation - "
                    f"context only, to be verified on inspection")
        if _closure_active(zone, day) and fishing:
            indicators.append({
                "kind": "zone", "zone": zone["name"], "zone_id": zone["id"],
                "rests_on_activity": True,
                "reason": (
                    f"contextual classifier indicates likely fishing activity "
                    f"(non-observational) during active closure "
                    f"({zone['closure']['reason']}) in '{zone['name']}' "
                    f"({zone['id']})"),
            })
            score_items.append((
                f"likely fishing during active closure ({zone['id']})",
                weights["zone_violation"]))

    # Corroboration only: the fishing classifier is contextual and never scores
    # on its own — the invariant score>0 ⟺ indicators holds.
    #
    # It is also withheld when an indicator already rests on the same signal. A
    # closure indicator, or an "all gear prohibited" indicator, exists only
    # because the classifier fired; awarding corroboration for it would count
    # one observation twice, and here that double count is what pushes a record
    # across the high-priority boundary.
    activity_already_counted = any(
        i.get("kind") == "zone" and i.get("rests_on_activity")
        for i in indicators)
    if fishing and indicators and not activity_already_counted:
        score_items.append((
            "contextual classifier indicates likely fishing activity "
            "(non-observational) - corroboration only",
            weights["fishing_context"]))

    # --- Fixed-infrastructure suppression (duty of caution, both directions).
    # A detection coinciding with a charted fixed structure must not raise a
    # dark-vessel candidate: every indicator computed above rests on reading a
    # stationary return as a vessel, and the fishing-activity classifier firing
    # on a platform is itself the false positive Task 4.1 names. Demote those
    # indicators to context and drop their points — but never silently: the
    # record is surfaced with a note so a human verifies no vessel is operating
    # alongside the structure (a known radar-shadow concealment tactic).
    fixed = _fixed_structure_match(detection, structures or [])
    if fixed:
        for ind in indicators:
            context.append(
                "suppressed as attributable to charted fixed structure "
                f"{fixed.get('id', '?')}: {ind['reason']}")
        indicators = []
        score_items = []
        ais_suppressed = False  # a structure is not a dark vessel; AIS is moot

    total = sum(points for _, points in score_items)

    ais_note = None
    if ais_suppressed:
        ais_note = ("Below the AIS carriage threshold: absence of an AIS "
                    "broadcast is not an indicator. Other indicators, if any, "
                    "remain.")
        # The VMS threshold is applied to the same noisy radar estimate as the
        # AIS one, so it gets the same uncertainty band. Stating the band is
        # what keeps the note a pointer to a cross-check rather than a claim.
        margin = sigma_k * sigma
        if length - margin >= vms_threshold:
            ais_note += (
                f" The appropriate cross-check is VMS: vessels of "
                f"{vms_threshold} m and over must carry an operational VMS "
                f"(since January 2026), and the authority already holds that "
                f"track.")
        elif length + margin >= vms_threshold:
            ais_note += (
                f" The estimated length is within sensor uncertainty of the "
                f"{vms_threshold} m VMS threshold, so a VMS cross-check may or "
                f"may not apply; the authority can settle this from its own "
                f"records.")

    # Classification follows the number of independent indicators that concur,
    # not a points total. Points were previously tuned around a corroboration
    # item that double-counted the activity classifier; removing that double
    # count moved records across a threshold it had helped set, which is proof
    # the threshold was measuring the wrong thing. Counting indicators is the
    # claim we already make to the reader ("N independent indicators concur"),
    # and the weights now do only what the README says they do: order records
    # within a class.
    # Only a firm indicator can make a record an inspection candidate. A
    # degraded one — a length estimate that does not clear the threshold once
    # its own uncertainty is applied — may corroborate a candidacy raised by
    # something else, but cannot raise one alone. Without this, a 14 m estimate
    # against a 15 m threshold with +/-2 m of sensor error would put a vessel on
    # the patrol route on the strength of an indicator whose own text says
    # "inconclusive", and would create a cliff between 13 m and 14 m on a
    # measurement that cannot resolve the difference.
    firm = [i for i in indicators if not i.get("degraded")]
    degraded_only = len(indicators) - len(firm)

    if fixed:
        classification = "fixed_structure"
        note = (
            f"Coincides with charted fixed structure {fixed.get('id', '?')} "
            f"({fixed.get('type', 'unknown')}). The radar return is attributable "
            f"to infrastructure, so no dark-vessel candidate is raised; verify on "
            f"inspection that no vessel is operating alongside it.")
    elif len(firm) >= HIGH_INDICATOR_COUNT:
        classification = "high_priority"
        note = f"{len(firm)} independent indicators concur."
    elif firm:
        classification = "medium_priority"
        note = (f"{len(firm)} indicator; partial, requires corroboration."
                + (f" {degraded_only} further indicator(s) are degraded and "
                   f"corroborate only." if degraded_only else ""))
    elif indicators:
        classification = "below_candidate_threshold"
        note = (f"{degraded_only} degraded indicator(s) only: recorded, but not "
                f"sufficient to raise an inspection candidate.")
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
    if fixed:
        record["fixed_structure"] = {
            "id": fixed.get("id"), "type": fixed.get("type"),
            "name": fixed.get("name"),
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
    # Charted fixed infrastructure (platforms, wind turbines, buoys, aquaculture)
    # is a reference layer, parallel to the zones. Absent by default, so the
    # engine's behaviour is unchanged until the authority supplies its registry.
    structures = zones_doc.get("fixed_structures", [])
    scene = detections_doc["scene"]
    day = _scene_date(scene)

    records = [assess_detection(d, zones, config, day, structures)
               for d in detections_doc["detections"]]

    order = {"high_priority": 0, "medium_priority": 1,
             "below_candidate_threshold": 2, "fixed_structure": 3,
             "no_indicators": 4, "ais_not_applicable": 5}
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
        # Step 1 of the agentic loop: was this night even propitious for angula?
        # A scanning-priority signal, never a per-vessel indicator (see
        # environment.py). Reported so the analyst can weigh whether the scene
        # merited attention, not to incriminate any boat.
        "environmental_context": environment.angula_conditions(
            scene.get("timestamp"), config),
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
        "fixed_structure_suppressed": [r for r in records
                                       if r["classification"] == "fixed_structure"],
    }
