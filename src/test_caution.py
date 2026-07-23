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

    passed = sum(results)
    print(f"\n{passed}/{len(results)} checks passed\n")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
