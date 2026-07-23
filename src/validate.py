"""Output validation.

Prompting alone does not guarantee the guarantees. Models follow instructions
approximately, and in this system an approximate answer can attach a breach to a
compliant vessel, move a coordinate, or silently drop a vessel the dossier says
must be inspected. The duty runs in both directions: over-reporting accuses
without basis, under-reporting lets a high-priority target disappear.

So the model's output is checked against the factual dossier in code, before a
human ever reads it. Both agent outputs are validated: the analyst's
prioritisation and the writer's report. This module is deterministic: no API
key, no network.

Severity:
  BLOCKER  the output must not be shown to an inspector as it stands
  WARNING  defensible but likely wrong; a human should look
"""

import re

BLOCKER = "BLOCKER"
WARNING = "WARNING"

# Wording that indicates the AIS carriage requirement is being invoked.
# output_language is configurable, so the patterns cover Spanish as well as
# English: "artículo/articulo 10", "Reglamento (CE) ... 1224", "1224/2009".
_AIS_PATTERNS = [
    r"\bais\b",
    r"carriage requirement",
    r"article\s*10",
    r"art[íi]culo\s*10",
    r"\bart\.?\s*10\b",
    r"1224/2009",
    r"reglamento\s*\(ce\)\s*n?\S*\s*1224",
]

# Degrees of latitude/longitude. ~1 km at these latitudes: generous enough for
# formatting round-trips, far too small for the model to relocate a vessel.
_POSITION_TOLERANCE_DEG = 0.01


def _mentions_ais(text: str) -> bool:
    lowered = (text or "").lower()
    return any(re.search(p, lowered) for p in _AIS_PATTERNS)


def _records_by_id(dossier: dict) -> dict:
    return {r["id"]: r for r in dossier.get("records", [])}


def _silently_suppressed_ids(dossier: dict) -> set:
    """Vessels whose AIS indicator is suppressed AND that have no other
    indicators. These must never surface in prose as if they were suspicious.
    A suppressed vessel WITH zone indicators is a legitimate candidate and may
    appear — the suppression removes the AIS indicator, not the vessel."""
    return {r["id"] for r in dossier.get("ais_indicator_suppressed", [])
            if not r.get("potential_indicators")}


def _parse_position(value):
    """Accept {"lat": .., "lon": ..} or a "lat, lon" string. None if unusable."""
    if isinstance(value, dict):
        try:
            return float(value.get("lat")), float(value.get("lon"))
        except (TypeError, ValueError):
            return None
    if isinstance(value, str):
        numbers = re.findall(r"-?\d+(?:\.\d+)?", value)
        if len(numbers) >= 2:
            return float(numbers[0]), float(numbers[1])
    return None


def _ais_engaged(record: dict) -> bool:
    """True when the record's own indicator list contains an AIS indicator."""
    return any(str(i.get("kind", "")).startswith("ais")
               for i in record.get("potential_indicators", []))


def validate_report(dossier: dict, report: dict) -> list:
    """Check a writer-agent report against the dossier. Returns a list of issues."""
    issues = []
    records = _records_by_id(dossier)
    silent_ids = _silently_suppressed_ids(dossier)
    briefs = report.get("inspection_briefs", []) or []
    briefed_ids = set()

    for brief in briefs:
        vessel_id = brief.get("id")
        briefed_ids.add(vessel_id)
        record = records.get(vessel_id)
        where = f"brief {vessel_id}"

        if record is None:
            issues.append((BLOCKER, where,
                           "brief refers to a detection that is not in the dossier"))
            continue

        # 1. A vessel with the AIS indicator suppressed and nothing else must
        #    never get a brief.
        if vessel_id in silent_ids:
            issues.append((BLOCKER, where,
                           "the AIS indicator is suppressed for this vessel and "
                           "it has no other indicators, yet it has a brief"))

        # 2. Only high- and medium-priority records warrant a brief.
        if record["classification"] not in ("high_priority", "medium_priority"):
            issues.append((WARNING, where,
                           f"classification is {record['classification']}, "
                           f"which does not warrant a brief"))

        broadcasting = record.get("ais") == "matched"
        ais_ok = _ais_engaged(record)
        regulation = brief.get("regulation_concerned", "") or ""
        caveat = brief.get("caveat", "") or ""
        action = str(brief.get("suggested_action", "") or "")
        indicators_text = " ".join(str(i) for i in brief.get("indicators", []) or [])
        has_indicators = bool(record.get("potential_indicators"))

        # 3. Never invoke the carriage requirement when the record's own
        #    indicator list does not engage it — whether the vessel is
        #    broadcasting, below the threshold, or of unknown AIS status.
        if not ais_ok:
            why = ("vessel is broadcasting" if broadcasting
                   else "the AIS indicator is suppressed or not raised "
                        "for this vessel")
            for field_name, text in (("the regulation cited", regulation),
                                     ("the indicators list", indicators_text),
                                     ("the suggested action", action)):
                if _mentions_ais(text):
                    issues.append((BLOCKER, where,
                                   f"{why}, yet {field_name} invokes the AIS "
                                   f"carriage requirement"))
        if broadcasting and _mentions_ais(caveat):
            issues.append((WARNING, where,
                           "vessel is broadcasting, yet the caveat discusses AIS"))

        # 4. Positions are computed, never written: the brief's position must
        #    match the dossier record within tolerance.
        position = _parse_position(brief.get("position"))
        if position is None:
            issues.append((WARNING, where,
                           "position is missing or unparseable"))
        else:
            ref = record["position"]
            if (abs(position[0] - ref["lat"]) > _POSITION_TOLERANCE_DEG
                    or abs(position[1] - ref["lon"]) > _POSITION_TOLERANCE_DEG):
                issues.append((BLOCKER, where,
                               f"position {position[0]}, {position[1]} does not "
                               f"match the dossier position {ref['lat']}, "
                               f"{ref['lon']}: coordinates must never be "
                               f"altered by the model"))

        # 5. Do not report "none identified" when indicators exist.
        if has_indicators and re.search(r"none identified|not applicable|^none$",
                                        regulation.strip().lower()):
            issues.append((WARNING, where,
                           f"record has {len(record['potential_indicators'])} "
                           f"indicator(s) but no regulation is named"))

        # 6. Do not name a regulation when the record has no indicators at all.
        if not has_indicators and regulation.strip() and not re.search(
                r"none identified|not applicable", regulation.strip().lower()):
            issues.append((BLOCKER, where,
                           "record has no indicators, yet a regulation is named"))

    # 7. The duty runs in both directions: every high-priority record in the
    #    dossier must have a brief. Silent omission is a blocker.
    for record in dossier.get("records", []):
        if (record["classification"] == "high_priority"
                and record["id"] not in briefed_ids):
            issues.append((BLOCKER, f"brief {record['id']}",
                           "high-priority record has no inspection brief: the "
                           "duty of caution runs in both directions and the "
                           "report must not under-report"))

    # 8. Free prose must not reintroduce vessels whose AIS indicator is
    #    suppressed and that have no other indicators.
    prose_fields = ["executive_summary", "methodological_note",
                    "human_decision_required"]
    prose = " ".join(str(report.get(f, "")) for f in prose_fields)
    for vessel_id in sorted(silent_ids):
        if vessel_id in prose:
            issues.append((BLOCKER, "narrative",
                           f"{vessel_id} has its AIS indicator suppressed and no "
                           f"other indicators, yet appears in the narrative"))

    return issues


def validate_prioritisation(dossier: dict, prioritisation: dict) -> list:
    """Check the analyst-agent output against the dossier."""
    issues = []
    records = _records_by_id(dossier)
    candidate_ids = {r["id"] for r in dossier.get("inspection_candidates", [])}
    silent_ids = _silently_suppressed_ids(dossier)

    for candidate in prioritisation.get("prioritised_candidates", []) or []:
        vessel_id = candidate.get("id")
        where = f"prioritised {vessel_id}"
        if vessel_id not in records:
            issues.append((BLOCKER, where,
                           "prioritised id does not exist in the dossier"))
        elif vessel_id not in candidate_ids:
            issues.append((BLOCKER, where,
                           f"prioritised id is not an inspection candidate "
                           f"(classification: "
                           f"{records[vessel_id]['classification']})"))

    prose = " ".join([str(prioritisation.get("observed_pattern", "")),
                      str(prioritisation.get("overall_recommendation", ""))])
    for vessel_id in sorted(silent_ids):
        if vessel_id in prose:
            issues.append((BLOCKER, "analyst narrative",
                           f"{vessel_id} has its AIS indicator suppressed and no "
                           f"other indicators, yet appears in the analyst "
                           f"narrative"))

    return issues


def format_issues(issues: list) -> str:
    if not issues:
        return "Output validation: no issues."
    lines = [f"Output validation: {len(issues)} issue(s)"]
    for severity, where, message in issues:
        lines.append(f"  [{severity}] {where}: {message}")
    return "\n".join(lines)


def has_blockers(issues: list) -> bool:
    return any(severity == BLOCKER for severity, _, _ in issues)
