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
# The model copies a coordinate; it does not compute one. The tolerance
# only absorbs formatting rounding, not drift: 0.01 deg is ~1.1 km, enough
# to cross a zone boundary.
_POSITION_TOLERANCE_DEG = 0.001


def _mentions_ais(text: str) -> bool:
    lowered = (text or "").lower()
    return any(re.search(p, lowered) for p in _AIS_PATTERNS)



# Tokens that survive translation: zone identifiers, figures and legal
# references are written the same way in any working language. Comparing these
# gives a fidelity check that works in every language, rather than a word-
# overlap check that only works in the one language the authority will not use.
_INVARIANT_TOKEN = re.compile(
    r"[A-Z]{2,4}-\d{2,}"        # zone ids: RES-03, CLS-02, MPA-01
    r"|\d{4}/\d{4}"             # legal references: 1224/2009, 2023/2842
    # Figures, with either decimal separator: the engine writes 15.0 and a
    # Spanish brief writes 15,0. Matching only the dot would empty the
    # intersection for a record whose indicators are numeric, blocking a
    # faithful translation.
    r"|\d+[.,]\d+"              # figures: 22.0 / 22,0
)


# Models write RES\u201103 (non-breaking hyphen) as readily as RES-03, and 15,0
# as readily as 15.0. Neither is a fidelity failure, so both are normalised to
# the ASCII form before anything is matched or compared.
_DASH_VARIANTS = dict.fromkeys(map(ord, "\u2010\u2011\u2012\u2013\u2014\u2015"), "-")


def _normalise(text: str) -> str:
    return (text or "").translate(_DASH_VARIANTS)


def _invariant_tokens(text: str) -> set:
    return {t.replace(",", ".")
            for t in _INVARIANT_TOKEN.findall(_normalise(text))}


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
        lat, lon = value.get("lat"), value.get("lon")
        if lat is None or lon is None:
            return None
        try:
            return float(lat), float(lon)
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
    english_output = str(dossier.get("output_language", "English")).lower() == "english"
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
        action = str(brief.get("suggested_action", "") or "").strip()
        indicators_text = " ".join(str(i) for i in brief.get("indicators", []) or [])
        has_indicators = bool(record.get("potential_indicators"))
        # The record's own translation-invariant anchors: its zone ids, figures
        # and legal references. Rules 8 and 9 both compare against these, so
        # they are computed once here rather than twice below.
        record_tokens = _invariant_tokens(" ".join(
            i.get("reason", "") for i in record.get("potential_indicators", [])))

        # A. A record with potential indicators must always include a caveat 
        #    evaluating the context.
        if has_indicators and not caveat.strip():
            issues.append((BLOCKER, where,
                           "record has potential indicators, yet the mandatory caveat is missing"))

        # B. The caveat must not contradict the record's factual length. A
        #    vessel above the carriage threshold cannot be described as falling
        #    below it: that invites an inspector to dismiss a live indicator.
        #    The threshold comes from the dossier, not from a literal here — it
        #    is jurisdiction configuration, and a rule that hardcodes it would
        #    check the wrong number the moment a jurisdiction sets its own.
        threshold = dossier.get("ais_length_threshold_m")
        length = record.get("estimated_length_m")
        if threshold is not None and length is not None and float(length) >= float(threshold):
            below_claim = (rf"(under|below|less than)\s*{int(float(threshold))}"
                           rf"|menos de\s*{int(float(threshold))}|not meet|no alcanza")
            if re.search(below_claim, caveat.lower()):
                issues.append((BLOCKER, where,
                               f"the caveat describes the vessel as under the "
                               f"{threshold} m threshold, but the record gives "
                               f"{length} m"))

        # C. The suggested action must not exceed the inspector's authority. 
        #    An inspector can observe or contact, but not seize or arrest.
        forbidden_actions = r"\b(seize|confiscate|arrest|impound|incautar|detener|apresar|confiscar)\b"
        if re.search(forbidden_actions, action.lower()):
            issues.append((BLOCKER, where,
                           f"suggested action '{action}' exceeds inspector authority by invoking seizure or arrest"))

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
        if has_indicators and (not regulation.strip() or re.search(
                r"none identified|not applicable|^none$",
                regulation.strip().lower())):
            issues.append((WARNING, where,
                           f"record has {len(record['potential_indicators'])} "
                           f"indicator(s) but no regulation is named"))

        # 6. Do not name a regulation when the record has no indicators at all.
        if not has_indicators and regulation.strip() and not re.search(
                r"none identified|not applicable", regulation.strip().lower()):
            issues.append((BLOCKER, where,
                           "record has no indicators, yet a regulation is named"))

        # 7. The brief must state the priority the engine assigned. Rule 13
        #    checks that a high-priority record HAS a brief; it does not check
        #     that the brief says so. A record the engine ranked high, written
        #     up as "low", is under-reporting delivered in the one field an
        #     inspector uses to order the day.
        stated = str(brief.get("priority", "")).strip().lower()
        expected = record["classification"].replace("_priority", "").lower()
        if stated and stated not in (expected, record["classification"].lower()):
            issues.append((BLOCKER, where,
                           f"the brief states priority '{stated}' but the record "
                           f"is {record['classification']}"))

        # 8. The regulation must belong to THIS record. Rule 5 only checks
        #    that the field is not empty, and rule 9 checks the indicators,
        #     not this field — so two briefs could have their regulations
        #     swapped and pass both. Citing a provision that concerns another
        #     vessel is the exact error this system exists to prevent.
        #
        #     Matching on shared anchors is not enough: the threshold figure
        #     appears in every AIS indicator, so any two AIS citations always
        #     intersect. What identifies misattribution is the presence of an
        #     anchor that belongs exclusively to a DIFFERENT detection — this
        #     vessel's brief citing that vessel's length or zone.
        cited_tokens = _invariant_tokens(regulation)
        foreign = {}
        for other_id, other in records.items():
            if other_id == vessel_id:
                continue
            exclusive = _invariant_tokens(" ".join(
                i.get("reason", "") for i in
                other.get("potential_indicators", []))) - record_tokens
            for token in cited_tokens & exclusive:
                foreign[token] = other_id
        if foreign:
            detail = ", ".join(f"{t} ({i})" for t, i in sorted(foreign.items()))
            issues.append((BLOCKER, where,
                           f"the regulation cited carries anchors belonging to "
                           f"another detection: {detail}"))

        # 8b. The regulation field names provisions; it does not restate the
        #     indicators. A writer that pastes the indicator text here leaves
        #     the inspector reading the same paragraph twice and never seeing
        #     which rule is at stake. Detected by containment rather than
        #     length: a long citation is fine, a copy of an indicator is not.
        for indicator in record.get("potential_indicators", []):
            reason = (indicator.get("reason") or "").strip()
            if len(reason) > 40 and reason[:60].lower() in regulation.lower():
                issues.append((WARNING, where,
                               "the regulation field restates an indicator "
                               "instead of naming the provision it concerns"))
                break

        # 9. Fidelity across languages. The brief must restate the record's
        #    indicators rather than invent new ones, and word overlap cannot
        #     show that once the brief is a translation. Tokens that translation
        #     leaves untouched can: zone identifiers, figures and legal
        #     references. Checked over the brief as a whole, because a single
        #     indicator may legitimately carry none of them while another does.
        brief_tokens = _invariant_tokens(" ".join(
            str(x) for x in (brief.get("indicators") or [])))
        if record_tokens and not (brief_tokens & record_tokens):
            issues.append((BLOCKER, where,
                           "the brief's indicators cite none of the zone "
                           "identifiers, figures or legal references that "
                           "appear in the record's own indicators"))

        # 10. Rule 9 bounds substitution, not addition: a brief that keeps
        #    the record's anchors and appends an invented indicator satisfies
        #     it. Addition is the likelier failure — models embellish more often
        #     than they replace — and in an inspection brief an added line is a
        #     fresh accusation nobody observed. A brief may legitimately
        #     consolidate two indicators into one well-formed statement, so only
        #     an excess is a failure.
        brief_indicator_count = len(brief.get("indicators") or [])
        record_indicator_count = len(record.get("potential_indicators") or [])
        if brief_indicator_count > record_indicator_count:
            issues.append((BLOCKER, where,
                           f"the brief lists {brief_indicator_count} "
                           f"indicator(s) but the record contains "
                           f"{record_indicator_count}: the writer has added an "
                           f"indicator that no fact supports"))

        # 11. The suggested action must be an instruction. A model that writes
        #     only a distance ("40.77 km from base") has restated context; an
        #     inspector cannot act on it.
        #
        #     What matters is whether an instruction remains once the distance
        #     is set aside, not whether the action happens to open with one.
        #     An earlier version matched any action STARTING with a distance and
        #     flagged all seven briefs in a correct report, because the model had
        #     simply written "38.0 km from base: board and verify gear" — a
        #     perfectly actionable line with the range in front.
        instruction = re.sub(r"^[\d.,]+\s*(km|nm|miles)\b[^:.]*[:.]?\s*", "",
                             action, flags=re.IGNORECASE).strip()
        if not instruction or len(instruction) < 15:
            issues.append((WARNING, where,
                           f"suggested action '{action}' states context rather "
                           f"than an instruction the inspector can follow"))

        # 12. The brief's indicators must restate the record's indicators, not
        #    the analyst's shorthand labels. A model that writes "ais" or
        #     "zone" has copied a category name; an inspector cannot act on it.
        brief_indicators = brief.get("indicators") or []
        record_indicator_text = " ".join(
            i.get("reason", "") for i in record.get("potential_indicators", [])
        ).lower()
        for entry in brief_indicators:
            text = str(entry).strip()
            if len(text) < 25:
                issues.append((BLOCKER, where,
                               f"indicator '{text}' is a category label, not a "
                               f"statement an inspector can act on"))
                continue
            # Word overlap works only where brief and dossier share a language.
            words = {w for w in re.findall(r"[a-z]{4,}", text.lower())}
            if english_output and words and record_indicator_text and not (
                    words & set(re.findall(r"[a-z]{4,}", record_indicator_text))):
                issues.append((WARNING, where,
                               "indicator text shares no wording with the "
                               "record's own indicators"))

    # 13. The duty runs in both directions: every high-priority record in the
    #    dossier must have a brief. Silent omission is a blocker.
    for record in dossier.get("records", []):
        classification = record["classification"]
        if classification not in ("high_priority", "medium_priority"):
            continue
        if record["id"] in briefed_ids:
            continue
        severity = BLOCKER if classification == "high_priority" else WARNING
        issues.append((severity, f"brief {record['id']}",
                       f"{classification} record has no inspection brief: the "
                       f"duty of caution runs in both directions and the report "
                       f"must not under-report"))

    # 14. Free prose must not reintroduce vessels whose AIS indicator is
    #    suppressed and that have no other indicators.
    prose_fields = ["executive_summary", "methodological_note",
                    "human_decision_required"]
    prose = " ".join(str(report.get(f, "")) for f in prose_fields)
    for problem in _misattributed_priorities(prose, records):
        issues.append((WARNING, "narrative", problem))

    for vessel_id in sorted(silent_ids):
        if vessel_id in prose:
            issues.append((BLOCKER, "narrative",
                           f"{vessel_id} has its AIS indicator suppressed and no "
                           f"other indicators, yet appears in the narrative"))

    return issues



# Priority words as they appear in narrative prose, mapped to the classification
# value they assert. Hyphen, en dash and non-breaking hyphen all occur in model
# output, so the pattern accepts any of them.
_DASH = r"[\s\u2010-\u2015-]*"
_ID_LIST = r"D-\d+(?:(?:\s*,\s*|\s+and\s+)D-\d+)*"

# Two constructions assert membership of a priority class:
#   "high-priority vessels (D-010, D-004)"   parenthesised list
#   "high-priority detections D-010 and D-004"   bare list
# In the bare form only unpunctuated words may sit between the priority term and
# the list, so "high-priority candidates first, then D-005" — which asserts
# nothing about D-005 — does not match.
_PRIORITY_CLAIMS = [
    # The window is generous because real sentences put words between the claim
    # and the list ("High-priority detections cluster west of the base, with
    # three vessels (D-010, ...)"). It must not cross a second priority term,
    # though: in "high-priority first, then the medium ones (D-005)" the list
    # belongs to the second claim, not the first.
    re.compile(rf"(high|medium){_DASH}priority"
               rf"((?:(?!high{_DASH}priority|medium{_DASH}priority)[^.(]){{0,100}})"
               rf"\(([^)]*)\)",
               re.IGNORECASE),
    re.compile(rf"(high|medium){_DASH}priority\s+(?:[a-zA-Z]+\s+){{0,3}}({_ID_LIST})",
               re.IGNORECASE),
]


def _misattributed_priorities(text: str, records: dict) -> list:
    """Find explicit claims of the form "high-priority vessels (D-1, D-2)".

    Deliberately narrow. A claim is only checked when the ids appear in a
    parenthesised list immediately after the priority term, because that is the
    construction that asserts membership. Looser proximity ("inspect the
    high-priority cluster first, then D-005") does not assert anything false and
    must not be flagged.
    """
    problems = []
    seen = set()
    for pattern in _PRIORITY_CLAIMS:
        for match in pattern.finditer(text or ""):
            claimed = f"{match.group(1).lower()}_priority"
            for vessel_id in re.findall(r"\bD-\d+\b", match.groups()[-1]):
                record = records.get(vessel_id)
                if not record or record["classification"] == claimed:
                    continue
                key = (vessel_id, claimed)
                if key in seen:
                    continue
                seen.add(key)
                problems.append(
                    f"{vessel_id} is {record['classification']} but the narrative "
                    f"lists it among {claimed} records")
    return problems


def _record_figures(record: dict) -> set:
    """Every figure and identifier the dossier legitimately holds for a record.

    Not just the indicator text: an analyst that writes "44.02 km from base" is
    quoting the dossier, and an earlier version of this check blocked four
    reports for exactly that, because it only looked at the indicators and the
    length. A rule that rejects the model for citing real data is worse than the
    fabrication it was written to catch.
    """
    figures = _invariant_tokens(" ".join(
        i.get("reason", "") for i in record.get("potential_indicators", [])))
    figures |= _invariant_tokens(" ".join(
        str(n) for n in record.get("contextual_notes", []) or []))

    for key in ("estimated_length_m", "distance_from_base_km", "fishing_score",
                "speed_kn", "score"):
        value = record.get(key)
        if value is not None:
            figures.add(str(value))

    position = record.get("position") or {}
    for key in ("lat", "lon"):
        if position.get(key) is not None:
            figures.add(str(position[key]))
            figures.add(str(abs(position[key])))   # written without the sign

    for zone in record.get("zones", []) or []:
        if zone.get("id"):
            figures.add(zone["id"])

    return figures


def validate_prioritisation(dossier: dict, prioritisation: dict) -> list:
    """Check the analyst-agent output against the dossier."""
    issues = []
    records = _records_by_id(dossier)
    candidate_ids = {r["id"] for r in dossier.get("inspection_candidates", [])}
    silent_ids = _silently_suppressed_ids(dossier)

    narrative = " ".join(str(prioritisation.get(f, "")) for f in
                         ("observed_pattern", "overall_recommendation"))
    for problem in _misattributed_priorities(narrative, records):
        issues.append((WARNING, "analyst narrative", problem))

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

    # The analyst's reason text is prose about a record, and until now nothing
    # compared it with that record. A real run stated "19.0 m" for a 55 m vessel
    # — the very figure that decides whether the carriage threshold applies —
    # and passed clean. Same anchor test as the writer's indicators: if the
    # reason carries figures or zone ids at all, at least one must be the
    # record's own. Reasons that paraphrase without citing anything are left
    # alone, because they assert no figure to be wrong about.
    for candidate in prioritisation.get("prioritised_candidates", []) or []:
        record = records.get(candidate.get("id"))
        if record is None:
            continue
        cited = _invariant_tokens(str(candidate.get("reason", "")))
        own = _record_figures(record)
        if cited and own and not (cited & own):
            issues.append((BLOCKER, f"prioritised {candidate.get('id')}",
                           f"the reason cites {sorted(cited)}, none of which "
                           f"appear in this record: the analyst has stated a "
                           f"figure or zone the dossier does not support"))

    prose = " ".join([str(prioritisation.get("observed_pattern", "")),
                      str(prioritisation.get("overall_recommendation", ""))])
    for vessel_id in sorted(silent_ids):
        if vessel_id in prose:
            issues.append((BLOCKER, "analyst narrative",
                           f"{vessel_id} has its AIS indicator suppressed and no "
                           f"other indicators, yet appears in the analyst "
                           f"narrative"))

    prioritised_ids = {c.get("id") for c in
                       prioritisation.get("prioritised_candidates", []) or []}
    for record in dossier.get("records", []):
        classification = record["classification"]
        if classification not in ("high_priority", "medium_priority"):
            continue
        if record["id"] in prioritised_ids:
            continue
        # Symmetric with the writer: dropping a high-priority record is a
        # blocker, dropping a medium one is visible but not fatal. An analyst
        # that silently shortens the list is under-reporting either way.
        severity = BLOCKER if classification == "high_priority" else WARNING
        issues.append((severity, "analyst prioritisation",
                       f"{record['id']} is {classification} in the dossier but "
                       f"the analyst did not prioritise it"))

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