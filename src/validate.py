"""Output validation.

Prompting alone does not guarantee the guarantees. Models follow instructions
approximately, and in this system an approximate answer can attach a breach to a
compliant vessel or reintroduce a vessel the law says we must leave alone.

So the model's output is checked against the factual dossier in code, before a
human ever reads it. This module is deterministic: no API key, no network.

Severity:
  BLOCKER  the output must not be shown to an inspector as it stands
  WARNING  defensible but likely wrong; a human should look
"""

import re

BLOCKER = "BLOCKER"
WARNING = "WARNING"

# Wording that indicates the AIS carriage requirement is being invoked.
_AIS_PATTERNS = [
    r"\bais\b",
    r"carriage requirement",
    r"article\s*10",
]


def _mentions_ais(text: str) -> bool:
    lowered = (text or "").lower()
    return any(re.search(p, lowered) for p in _AIS_PATTERNS)


def _records_by_id(dossier: dict) -> dict:
    return {r["id"]: r for r in dossier.get("records", [])}


def validate_report(dossier: dict, report: dict) -> list:
    """Check a writer-agent report against the dossier. Returns a list of issues."""
    issues = []
    records = _records_by_id(dossier)
    excluded_ids = {r["id"] for r in dossier.get("excluded_by_caution", [])}
    briefs = report.get("inspection_briefs", []) or []

    for brief in briefs:
        vessel_id = brief.get("id")
        record = records.get(vessel_id)
        where = f"brief {vessel_id}"

        if record is None:
            issues.append((BLOCKER, where,
                           "brief refers to a detection that is not in the dossier"))
            continue

        # 1. A vessel excluded by the duty of caution must never get a brief.
        if vessel_id in excluded_ids:
            issues.append((BLOCKER, where,
                           "vessel was excluded by the duty of caution but has a brief"))

        # 2. Only high- and medium-priority records warrant a brief.
        if not record["classification"].endswith("_priority"):
            issues.append((WARNING, where,
                           f"classification is {record['classification']}, "
                           f"which does not warrant a brief"))

        broadcasting = record.get("ais") == "matched"
        regulation = brief.get("regulation_concerned", "") or ""
        caveat = brief.get("caveat", "") or ""
        has_indicators = bool(record.get("potential_indicators"))

        # 3. Never invoke the carriage requirement against a broadcasting vessel.
        if broadcasting and _mentions_ais(regulation):
            issues.append((BLOCKER, where,
                           "vessel is broadcasting, yet the regulation cited "
                           "invokes the AIS carriage requirement"))
        if broadcasting and _mentions_ais(caveat):
            issues.append((WARNING, where,
                           "vessel is broadcasting, yet the caveat discusses AIS"))

        # 4. Do not report "none identified" when indicators exist.
        if has_indicators and re.search(r"none identified|not applicable|^none$",
                                        regulation.strip().lower()):
            issues.append((WARNING, where,
                           f"record has {len(record['potential_indicators'])} "
                           f"indicator(s) but no regulation is named"))

        # 5. Do not name a regulation when the record has no indicators at all.
        if not has_indicators and regulation.strip() and not re.search(
                r"none identified|not applicable", regulation.strip().lower()):
            issues.append((BLOCKER, where,
                           "record has no indicators, yet a regulation is named"))

    # 6. Free prose must not reintroduce vessels the duty of caution excluded.
    prose_fields = ["executive_summary", "methodological_note",
                    "human_decision_required"]
    prose = " ".join(str(report.get(f, "")) for f in prose_fields)
    for vessel_id in sorted(excluded_ids):
        if vessel_id in prose:
            issues.append((BLOCKER, "narrative",
                           f"{vessel_id} was excluded by the duty of caution but "
                           f"appears in the narrative"))

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
