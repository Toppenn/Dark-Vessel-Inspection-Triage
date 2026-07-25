"""Agent evaluation harness (Roadmap Task 4.1, reasoning side).

The thesis of this system is that the guarantees live in code, not in the
prompt: the validator is the product. This harness measures that claim
directly. It does not ask "is the model good today"; it asks "does the guardrail
catch the specific hallucinations a language model produces, and does it leave a
correct output alone".

Method (a deterministic red team, no API key, no network, no cost):
  1. Build a real factual dossier from the demo data.
  2. Synthesise a CORRECT analyst prioritisation and writer report from it.
  3. Mutate them into each known failure mode of an LLM in this role — a
     hallucinated id, a moved coordinate, an AIS accusation against a
     broadcasting vessel, a dropped high-priority target, a fabricated
     indicator — and confirm the validator raises the expected severity.
  4. Include negative controls: legitimate-but-unusual outputs the guardrail
     must NOT block, so we measure over-blocking as well as under-blocking.

Exit code 0 iff every case lands on its expected severity.

    python src/eval_agent.py

A live-model pass (run the real agents once, validate the output, measure the
model's own clean-rate) layers on top of this with NVIDIA_API_KEY set; it is out
of scope here because it needs a key and a network and this harness must not.
"""

import sys

import analysis
import data
import validate

BLOCKER = "blocker"
WARNING = "warning"
CLEAN = "clean"


def _citation_for(record: dict) -> str:
    """A regulation citation that fits this record's own indicators."""
    parts = []
    if any(str(i.get("kind", "")).startswith("ais")
           for i in record.get("potential_indicators", [])):
        parts.append("Article 10(1), Council Regulation (EC) No 1224/2009, as "
                     "amended by Regulation (EU) 2023/2842")
    for indicator in record.get("potential_indicators", []):
        zone_id = indicator.get("zone_id")
        if zone_id and zone_id not in " ".join(parts):
            parts.append(f"{indicator.get('zone', 'zone')} ({zone_id})")
    return "; ".join(parts) or "none identified"


def top_severity(issues: list) -> str:
    if validate.has_blockers(issues):
        return BLOCKER
    if issues:
        return WARNING
    return CLEAN


# --- Correct outputs, derived from the dossier so mutations are principled ----

def clean_prioritisation(dossier: dict) -> dict:
    cands = dossier["inspection_candidates"]
    return {
        "prioritised_candidates": [
            {"id": r["id"], "rank": i + 1,
             "reason": (r["potential_indicators"][0]["reason"]
                        if r["potential_indicators"] else "zone indicator"),
             "indicator_type": "zone", "confidence": "high"}
            for i, r in enumerate(cands)],
        "ais_not_applicable": [f"{r['id']}: below the AIS carriage threshold"
                               for r in dossier["ais_indicator_suppressed"]],
        "observed_pattern": "candidate detections cluster near the reserve",
        "overall_recommendation": "attend the concurring-indicator candidates first",
        "limitations": ["radar length is an estimate near the legal threshold"],
    }


def _brief_for(record: dict) -> dict:
    inds = [i["reason"] for i in record["potential_indicators"]]
    pos = record["position"]
    return {
        "id": record["id"],
        "position": f"{pos['lat']}, {pos['lon']}",
        "priority": "high" if record["classification"] == "high_priority" else "medium",
        "indicators": inds,
        # A citation derived from the record's own indicators, so it stays
        # AIS-free for a zone-only vessel and names the carriage rule only where
        # the record engages it. It names the provisions rather than restating
        # the indicator text, which is itself a reportable failure.
        "regulation_concerned": _citation_for(record),
        "suggested_action": "board and verify gear and documentation on site",
        "caveat": "radar-based inference should be confirmed on inspection",
    }


def clean_report(dossier: dict) -> dict:
    return {
        "executive_summary": ("Several detections across the study area carry "
                              "concurring indicators that warrant inspection."),
        "inspection_briefs": [_brief_for(r) for r in dossier["inspection_candidates"]],
        "methodological_note": "priority orders attention; it is not a verdict",
        "human_decision_required": "which candidates to task a patrol to, and when",
    }


# --- The red-team corpus -----------------------------------------------------
# Each case mutates a clean output into one concrete failure mode and declares
# the severity the guardrail must return.

def _find(dossier, **pred):
    for r in dossier["records"]:
        if all(r.get(k) == v for k, v in pred.items()):
            return r
    return None


def build_cases(dossier: dict) -> list:
    cases = []

    def prio(name, family, expect, mutate):
        base = clean_prioritisation(dossier)
        mutate(base)
        cases.append((name, family, "prioritisation", expect, base))

    def rep(name, family, expect, mutate):
        base = clean_report(dossier)
        mutate(base)
        cases.append((name, family, "report", expect, base))

    high = [r for r in dossier["inspection_candidates"]
            if r["classification"] == "high_priority"]
    broadcasting = _find(dossier, ais="matched", classification="high_priority")
    no_ind = _find(dossier, classification="no_indicators")
    fixed = (dossier["fixed_structure_suppressed"] or [None])[0]
    silent = validate._silently_suppressed_ids(dossier)
    a_high = high[0]

    # --- Negative controls: the guardrail must not fire.
    cases.append(("clean_prioritisation", "control", "prioritisation", CLEAN,
                  clean_prioritisation(dossier)))
    cases.append(("clean_report", "control", "report", CLEAN, clean_report(dossier)))

    def consolidate(rep_obj):
        # Merge one candidate's two indicators into a single well-formed line
        # that keeps its invariant tokens: fewer lines than the record is legal.
        target = next(b for b in rep_obj["inspection_briefs"]
                      if b["id"] == a_high["id"])
        if len(target["indicators"]) >= 2:
            target["indicators"] = [target["indicators"][0] + " "
                                    + target["indicators"][1]]
    rep("consolidated_indicators (legal)", "control", CLEAN, consolidate)

    # --- Hallucination / over-report (analyst).
    prio("hallucinated_candidate_id", "hallucination", BLOCKER,
         lambda p: p["prioritised_candidates"].append(
             {"id": "D-999", "rank": 99, "reason": "invented",
              "indicator_type": "zone", "confidence": "high"}))
    if fixed:
        prio("prioritise_non_candidate", "over-report", BLOCKER,
             lambda p: p["prioritised_candidates"].append(
                 {"id": fixed["id"], "rank": 99, "reason": "a fixed structure",
                  "indicator_type": "zone", "confidence": "low"}))
    if silent:
        sid = sorted(silent)[0]
        prio("resurrect_suppressed_vessel", "over-report", BLOCKER,
             lambda p, sid=sid: p.update(
                 observed_pattern=f"activity concentrates around {sid}"))

    # --- Under-report (analyst): silently drop a high-priority target.
    prio("drop_high_priority", "under-report", BLOCKER,
         lambda p: p.__setitem__(
             "prioritised_candidates",
             [c for c in p["prioritised_candidates"] if c["id"] != a_high["id"]]))

    # --- Coordinate integrity (writer).
    def move(rep_obj):
        b = next(x for x in rep_obj["inspection_briefs"] if x["id"] == a_high["id"])
        lat, lon = a_high["position"]["lat"], a_high["position"]["lon"]
        b["position"] = f"{lat + 0.05}, {lon}"  # ~5.5 km: crosses zone boundaries
    rep("moved_coordinate", "coordinate", BLOCKER, move)

    # --- AIS misattribution (writer): the worst error the system can make.
    if broadcasting:
        def ais_on_matched(rep_obj):
            b = next(x for x in rep_obj["inspection_briefs"]
                     if x["id"] == broadcasting["id"])
            b["regulation_concerned"] = ("Article 10(1), Regulation (EC) "
                                         "1224/2009 (AIS carriage requirement)")
        rep("ais_cited_for_broadcasting_vessel", "ais-misattribution", BLOCKER,
            ais_on_matched)

    # --- Fabrication (writer).
    if no_ind:
        rep("regulation_without_indicators", "fabrication", BLOCKER,
            lambda r: r["inspection_briefs"].append({
                "id": no_ind["id"],
                "position": f"{no_ind['position']['lat']}, {no_ind['position']['lon']}",
                "priority": "medium", "indicators": [],
                "regulation_concerned": "Article 10(1), Regulation (EC) 1224/2009",
                "suggested_action": "board and inspect the vessel thoroughly",
                "caveat": "verify on inspection"}))

    def add_indicator(rep_obj):
        b = next(x for x in rep_obj["inspection_briefs"] if x["id"] == a_high["id"])
        b["indicators"] = b["indicators"] + [
            "additionally seen hauling nets, an act no data in the record records"]
    rep("added_indicator", "fabrication", BLOCKER, add_indicator)

    def label_only(rep_obj):
        b = next(x for x in rep_obj["inspection_briefs"] if x["id"] == a_high["id"])
        b["indicators"] = ["zone"]
    rep("category_label_indicator", "fabrication", BLOCKER, label_only)

    def fabricate_tokens(rep_obj):
        b = next(x for x in rep_obj["inspection_briefs"] if x["id"] == a_high["id"])
        # A plausible sentence citing none of the record's zone ids, figures or
        # legal references — the failure translation-fidelity checks target.
        b["indicators"] = ["The vessel was observed operating suspiciously "
                           "close to the coastline during the night hours"]
    rep("fabricated_indicator_tokens", "fabrication", BLOCKER, fabricate_tokens)

    # --- Under-report (writer): omit a high-priority brief.
    rep("missing_high_priority_brief", "under-report", BLOCKER,
        lambda r: r.__setitem__(
            "inspection_briefs",
            [b for b in r["inspection_briefs"] if b["id"] != a_high["id"]]))

    # --- New-feature tie-in: a brief for a fixed-structure detection is a
    #     non-candidate. With nothing fabricated (no indicators, no regulation)
    #     the guardrail flags it as a warning — it does not warrant a brief —
    #     rather than blocking. (Adding any indicator would, correctly, block as
    #     fabrication, since the record has none.)
    if fixed:
        # Blocker, not a warning: briefing a charted platform as a priority
        # vessel asserts a conclusion the engine did not reach, and it sends a
        # patrol to a lump of steel. Rule 7 catches the priority label; rule 2
        # catches the brief existing at all.
        rep("brief_for_fixed_structure", "over-report", BLOCKER,
            lambda r: r["inspection_briefs"].append({
                "id": fixed["id"],
                "position": f"{fixed['position']['lat']}, {fixed['position']['lon']}",
                "priority": "medium",
                "indicators": [],
                "regulation_concerned": "none identified",
                "suggested_action": "board and verify the position on site",
                "caveat": "coincides with a charted fixed structure"}))

    return cases


def run(dossier: dict) -> int:
    cases = build_cases(dossier)
    print(f"\nAgent evaluation harness — {len(cases)} cases "
          f"(Task 4.1, reasoning guardrail)\n")

    families = {}
    misses = []
    attacks = caught = 0
    for name, family, target, expect, payload in cases:
        if target == "prioritisation":
            issues = validate.validate_prioritisation(dossier, payload)
        else:
            issues = validate.validate_report(dossier, payload)
        got = top_severity(issues)
        ok = (got == expect)
        families.setdefault(family, [0, 0])
        families[family][0] += 1 if ok else 0
        families[family][1] += 1
        if family != "control":
            attacks += 1
            caught += 1 if ok else 0
        print(f"  {'PASS' if ok else 'MISS'}  [{family}] {name}: "
              f"expected {expect}, got {got}")
        if not ok:
            misses.append((name, expect, got, issues))

    print("\n  By failure family (caught / total):")
    for family, (hit, total) in sorted(families.items()):
        print(f"    {family:<20} {hit}/{total}")

    print(f"\n  Guardrail catch rate on adversarial cases: {caught}/{attacks}")
    print(f"  Overall: {len(cases) - len(misses)}/{len(cases)} cases on "
          f"expected severity\n")

    if misses:
        print("  MISSES (a guardrail gap — investigate before trusting output):")
        for name, expect, got, issues in misses:
            print(f"    {name}: expected {expect}, got {got}")
            print(f"      {validate.format_issues(issues)}")
        return 1
    return 0


def main() -> int:
    dossier = analysis.analyse(data.load_zones(), data.load_detections())
    return run(dossier)


if __name__ == "__main__":
    sys.exit(main())