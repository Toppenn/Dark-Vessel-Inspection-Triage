"""Safety tests for the duty of caution.

The duty of caution is the property that makes this system legitimate rather
than a suspicion generator, so it is tested rather than merely documented.

These tests run against the deterministic engine only: no API key, no network,
no cost. Run them before every commit.

    python src/test_caution.py
"""

import sys

import analysis
import data
import validate


def check(condition: bool, description: str) -> bool:
    print(f"  {'PASS' if condition else 'FAIL'}  {description}")
    return condition


def main() -> int:
    zones_doc = data.load_zones()
    detections_doc = data.load_detections()
    threshold = zones_doc["config"]["ais_length_threshold_m"]
    dossier = analysis.analyse(zones_doc, detections_doc)

    results = []
    print("\nDuty of caution")

    # 1. Every sub-threshold dark vessel must be classified non-assessable.
    should_be_excluded = {
        d["id"] for d in detections_doc["detections"]
        if not d.get("ais_matched", False)
        and d.get("estimated_length_m", 0) < threshold
    }
    actually_excluded = {r["id"] for r in dossier["excluded_by_caution"]}
    results.append(check(
        should_be_excluded == actually_excluded,
        f"all {len(should_be_excluded)} sub-threshold dark vessels excluded "
        f"(expected {sorted(should_be_excluded)}, got {sorted(actually_excluded)})"))

    # 2. An excluded vessel must never appear as an inspection candidate,
    #    even when it sits inside a regulated zone.
    candidate_ids = {r["id"] for r in dossier["inspection_candidates"]}
    results.append(check(
        not (actually_excluded & candidate_ids),
        "no excluded vessel appears among inspection candidates"))

    # 3. Excluded vessels must score exactly zero.
    excluded_scores = {r["id"]: r["score"] for r in dossier["excluded_by_caution"]}
    results.append(check(
        all(s == 0 for s in excluded_scores.values()),
        f"all excluded vessels score zero ({excluded_scores})"))

    # 4. Regression guard: at least one excluded vessel is inside a regulated
    #    zone. If the demo data ever loses this case, the test above becomes
    #    vacuous and would silently stop protecting anything.
    inside_zone = [
        r for r in dossier["records"]
        if r["classification"] == "non_assessable" and r["zones"]
    ]
    results.append(check(
        len(inside_zone) > 0,
        "test data still contains an excluded vessel inside a regulated zone "
        f"({[r['id'] for r in inside_zone]})"))

    print("\nScoring integrity")

    # 5. Every score must equal the sum of its itemised breakdown: no score
    #    may appear without a stated reason.
    mismatches = [
        r["id"] for r in dossier["records"]
        if r["classification"] != "non_assessable"
        and r["score"] != sum(i["points"] for i in r["score_breakdown"])
    ]
    results.append(check(
        not mismatches,
        f"every score equals the sum of its stated reasons ({len(dossier['records'])} records)"))

    # 6. An AIS-matched vessel must still be able to be flagged: identified is
    #    not the same as compliant.
    matched_flagged = [
        r for r in dossier["inspection_candidates"] if r["ais"] == "matched"
    ]
    results.append(check(
        len(matched_flagged) > 0,
        f"identified vessels can still be flagged ({[r['id'] for r in matched_flagged]})"))

    print("\nOutput validation")

    # The validator is fed the exact failures observed in real model output, so
    # that a regression in the guardrails is caught without an API call.
    excluded_id = dossier["excluded_by_caution"][0]["id"]
    matched = next(r for r in dossier["inspection_candidates"]
                   if r["ais"] == "matched")
    dark = next(r for r in dossier["inspection_candidates"]
                if r["ais"] != "matched")

    bad_report = {
        "executive_summary": (
            f"All vessels are dark. Two additional dark vessels ({excluded_id}) "
            f"were detected inside the active closure."),
        "inspection_briefs": [
            {"id": matched["id"], "priority": "medium",
             "regulation_concerned": "Article 10(1), Council Regulation (EC) No 1224/2009",
             "caveat": "the master may switch off AIS for crew safety"},
            {"id": dark["id"], "priority": "high",
             "regulation_concerned": "none identified",
             "caveat": "AIS technical failure"},
        ],
        "methodological_note": "single snapshot",
        "human_decision_required": "whether to dispatch",
    }
    bad = validate.validate_report(dossier, bad_report)
    kinds = {(sev, msg) for sev, _, msg in bad}

    results.append(check(
        any("broadcasting" in m and "carriage" in m for _, m in kinds),
        "flags the AIS carriage requirement cited against a broadcasting vessel"))
    results.append(check(
        any("appears in the narrative" in m for _, m in kinds),
        "flags an excluded vessel reintroduced in the narrative"))
    results.append(check(
        any("no regulation is named" in m for _, m in kinds),
        "flags a record with indicators but no regulation named"))
    results.append(check(
        validate.has_blockers(bad),
        "classifies these as blocking issues"))

    # A clean report over the same dossier must produce no issues at all,
    # otherwise the validator is simply complaining about everything.
    good_report = {
        "executive_summary": "Six vessels warrant inspection.",
        "inspection_briefs": [
            {"id": dark["id"], "priority": "high",
             "regulation_concerned": "Article 10(1), Council Regulation (EC) No 1224/2009",
             "caveat": "the master may switch off AIS for crew safety"},
            {"id": matched["id"], "priority": "medium",
             "regulation_concerned": "seasonal closure CLS-02, prohibited gear",
             "caveat": "gear inference from radar may be wrong"},
        ],
        "methodological_note": "single snapshot",
        "human_decision_required": "whether to dispatch",
    }
    clean = validate.validate_report(dossier, good_report)
    results.append(check(not clean,
                         f"passes a well-formed report with no false alarms ({clean})"))

    passed = sum(results)
    print(f"\n{passed}/{len(results)} checks passed\n")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
