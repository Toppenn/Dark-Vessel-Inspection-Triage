"""Safety tests for the duty of caution and the scoring invariant.

The duty of caution is the property that makes this system legitimate rather
than a suspicion generator — in BOTH directions. The AIS indicator is
suppressed for vessels below the carriage threshold, but ONLY that indicator:
zone violations remain, so a small dark vessel trawling inside an integral
reserve is still a candidate. And no vessel scores a single point without a
concrete indicator.

These tests run against the deterministic engine only: no API key, no network,
no cost. Run them before every commit.

    python src/test_caution.py
"""

import copy
import sys

import analysis
import data
import validate


def check(condition: bool, description: str) -> bool:
    print(f"  {'PASS' if condition else 'FAIL'}  {description}")
    return bool(condition)


def det(det_id, lat, lon, length, ais_matched=False, fishing=0.0,
        gear="unknown", **extra) -> dict:
    d = {"id": det_id, "lat": lat, "lon": lon, "estimated_length_m": length,
         "fishing_score": fishing, "likely_gear": gear}
    if ais_matched is not None:  # None = omit the field entirely
        d["ais_matched"] = ais_matched
    d.update(extra)
    return d


def raises_value_error(fn, *args):
    try:
        fn(*args)
        return None
    except ValueError as exc:
        return exc


def has_ais_indicator(record: dict) -> bool:
    return any(str(i.get("kind", "")).startswith("ais")
               for i in record["potential_indicators"])


def main() -> int:
    zones_doc = data.load_zones()
    detections_doc = data.load_detections()
    config = zones_doc["config"]
    zones = zones_doc["zones"]
    day = analysis._scene_date(detections_doc["scene"])
    dossier = analysis.analyse(zones_doc, detections_doc)

    records = {r["id"]: r for r in dossier["records"]}
    candidate_ids = {r["id"] for r in dossier["inspection_candidates"]}
    suppressed = {r["id"]: r for r in dossier["ais_indicator_suppressed"]}

    results = []
    print("\nDuty of caution: suppression is per-indicator, not per-vessel")

    # 1. Suppressed records never carry an AIS indicator or AIS points.
    results.append(check(
        all(not has_ais_indicator(r)
            and not any("AIS" in b["factor"] for b in r["score_breakdown"])
            for r in suppressed.values()),
        f"suppressed records carry no AIS indicator and no AIS points "
        f"({sorted(suppressed)})"))

    # 2. Acceptance: a 9 m dark vessel trawling inside the integral reserve is
    #    a candidate on its zone indicator alone.
    small_active = analysis.assess_detection(
        det("T-RES", 36.5, -6.75, 9.0, ais_matched=False, fishing=0.9,
            gear="bottom_trawl"), zones, config, day)
    results.append(check(
        small_active["classification"] in ("high_priority", "medium_priority")
        and any(i["kind"] == "zone" for i in small_active["potential_indicators"])
        and not has_ais_indicator(small_active)
        and small_active["ais_indicator_suppressed"],
        "9 m dark vessel trawling in an integral reserve is a candidate on its "
        "zone indicator, with the AIS indicator suppressed"))

    # 3. Acceptance: a 9 m dark vessel with nothing else scores zero.
    small_silent = analysis.assess_detection(
        det("T-OPEN", 36.0, -6.0, 9.0, ais_matched=False, fishing=0.2,
            gear="small_scale"), zones, config, day)
    results.append(check(
        small_silent["score"] == 0
        and not small_silent["potential_indicators"]
        and small_silent["classification"] == "ais_not_applicable",
        "9 m dark vessel with no other indicia scores 0 with no indicators"))

    # 4. Demo regression: D-005 is a candidate via zone indicators; D-007 and
    #    D-011 (no zone violation) stay at zero.
    results.append(check(
        "D-005" in candidate_ids and "D-005" in suppressed
        and bool(suppressed["D-005"]["potential_indicators"]),
        "demo: D-005 (dark, sub-threshold, fishing in integral reserve) is a "
        "candidate through its zone indicators"))
    results.append(check(
        all(records[i]["score"] == 0 and not records[i]["potential_indicators"]
            and i not in candidate_ids for i in ("D-007", "D-011")),
        "demo: D-007 and D-011 (sub-threshold, no zone violation) score 0"))

    # 5. Regression guard: the demo data must keep both discriminating cases,
    #    otherwise the two tests above go vacuous.
    results.append(check(
        any(r["potential_indicators"] for r in suppressed.values())
        and any(r["zones"] and not r["potential_indicators"]
                for r in suppressed.values()),
        "demo data keeps a suppressed vessel WITH zone indicators and a "
        "suppressed vessel inside a zone WITHOUT indicators"))

    # 6. Every suppressed record explains itself; 12 m+ records point to VMS.
    results.append(check(
        all("not an indicator" in r.get("ais_note", "")
            for r in suppressed.values())
        and "VMS" in suppressed["D-007"]["ais_note"],
        "suppressed records carry the caution note; 12 m+ records point to the "
        "VMS cross-check"))

    print("\nScoring invariant: score > 0 iff indicators exist")

    # 7. The hard invariant, no classification exceptions.
    results.append(check(
        all((r["score"] > 0) == bool(r["potential_indicators"])
            for r in dossier["records"]),
        f"score > 0 iff potential_indicators non-empty, for all "
        f"{len(dossier['records'])} records"))

    # 8. Zone presence alone scores nothing.
    transit = analysis.assess_detection(
        det("T-TRANSIT", 36.7, -7.0, 40.0, ais_matched=True, fishing=0.1,
            gear="in_transit", flag="ESP"), zones, config, day)
    results.append(check(
        transit["score"] == 0 and not transit["potential_indicators"],
        "matched vessel in transit inside an MPA has no indicators and no score"))

    # 9. Fishing-like movement alone scores nothing (D-012, outside all zones).
    results.append(check(
        records["D-012"]["score"] == 0
        and not records["D-012"]["potential_indicators"],
        "contextual fishing signal alone (D-012, open water) does not score"))

    # 10. Every score equals the sum of its itemised breakdown, and the
    #     double-counting '+15 provision concerned' item is gone.
    results.append(check(
        all(r["score"] == sum(i["points"] for i in r["score_breakdown"])
            for r in dossier["records"])
        and all("regulatory provision" not in i["factor"]
                for r in dossier["records"] for i in r["score_breakdown"]),
        "breakdowns sum exactly and contain no double-counting item"))

    # 11. Candidates are only high- and medium-priority records.
    results.append(check(
        all(r["classification"] in ("high_priority", "medium_priority")
            for r in dossier["inspection_candidates"]),
        "inspection candidates contain only high- and medium-priority records"))

    # 12. An AIS-matched vessel can still be flagged.
    matched_flagged = [r for r in dossier["inspection_candidates"]
                       if r["ais"] == "matched"]
    results.append(check(
        len(matched_flagged) > 0,
        f"identified vessels can still be flagged "
        f"({[r['id'] for r in matched_flagged]})"))

    print("\nLegal threshold: strict comparison, with an uncertainty band")

    # 13. "Exceeding" is strict (checked with sigma = 0 to isolate the bound).
    exact_config = copy.deepcopy(config)
    exact_config["length_sigma_m"] = 0.0
    at_threshold = analysis.assess_detection(
        det("T-15", 36.0, -6.0, 15.0, ais_matched=False, fishing=0.9,
            gear="bottom_trawl"), zones, exact_config, day)
    just_above = analysis.assess_detection(
        det("T-15PLUS", 36.0, -6.0, 15.01, ais_matched=False, fishing=0.9,
            gear="bottom_trawl"), zones, exact_config, day)
    results.append(check(
        at_threshold["ais_indicator_suppressed"]
        and not at_threshold["potential_indicators"]
        and has_ais_indicator(just_above),
        "'exceeding' is strict: a 15.0 m dark vessel is not covered, "
        "15.01 m is (sigma = 0)"))

    # 14. Near-threshold lengths yield a degraded, clearly labelled indicator
    #     worth fewer points than a firm one (default sigma).
    near = analysis.assess_detection(
        det("T-NEAR", 36.0, -6.0, 14.5, ais_matched=False, fishing=0.9,
            gear="bottom_trawl"), zones, config, day)
    firm = analysis.assess_detection(
        det("T-FIRM", 36.0, -6.0, 30.0, ais_matched=False, fishing=0.9,
            gear="bottom_trawl"), zones, config, day)
    results.append(check(
        near["ais_applicability"] == analysis.AIS_INCONCLUSIVE
        and any(i["kind"] == "ais_inconclusive"
                for i in near["potential_indicators"])
        and "inconclusive" in near["potential_indicators"][0]["reason"]
        and near["score"] < firm["score"],
        "length near the threshold gives a degraded 'inconclusive' indicator "
        "with fewer points than a firm one"))

    print("\nError policy: malformed critical data fails loudly")

    # 15. Missing or non-numeric length raises, naming the detection.
    exc = raises_value_error(
        analysis.assess_detection,
        det("T-NOLEN", 36.0, -6.0, None), zones, config, day)
    results.append(check(
        exc is not None and "T-NOLEN" in str(exc),
        "missing estimated_length_m raises ValueError naming the detection"))
    exc = raises_value_error(
        analysis.assess_detection,
        det("T-BADLEN", 36.0, -6.0, "12"), zones, config, day)
    results.append(check(
        exc is not None and "T-BADLEN" in str(exc),
        "non-numeric estimated_length_m raises ValueError"))

    # 16. Missing ais_matched is 'unknown', never assumed dark.
    unknown = analysis.assess_detection(
        det("T-UNK", 36.72, -7.05, 34.0, ais_matched=None, fishing=0.9,
            gear="bottom_trawl"), zones, config, day)
    results.append(check(
        unknown["ais_status"] == "unknown"
        and not has_ais_indicator(unknown)
        and not any("AIS" in b["factor"] for b in unknown["score_breakdown"]),
        "missing ais_matched gives status 'unknown': darkness is not assumed "
        "and no AIS indicator or points are produced"))

    # 17. Invalid scene timestamp raises instead of defaulting to today.
    exc = raises_value_error(
        analysis.analyse, zones_doc,
        {"scene": {"timestamp": "not-a-date"}, "detections": []})
    results.append(check(
        exc is not None,
        "invalid scene timestamp raises instead of silently using today"))

    # 18. A malformed closure raises instead of being treated as inactive.
    bad_zones = copy.deepcopy(zones)
    bad_zones[1]["closure"] = {"start": "junk", "end": "2026-09-30",
                               "reason": "spawning season"}
    exc = raises_value_error(
        analysis.assess_detection,
        det("T-CLS", 37.0, -6.9, 20.0, ais_matched=True, fishing=0.9,
            gear="bottom_trawl", flag="ESP"), bad_zones, config, day)
    results.append(check(
        exc is not None and "CLS-02" in str(exc),
        "malformed closure raises ValueError naming the zone"))

    print("\nOutput validation: writer report")

    matched_c = next(r for r in dossier["inspection_candidates"]
                     if r["ais"] == "matched")
    dark_c = next(r for r in dossier["inspection_candidates"]
                  if r["ais"] != "matched" and has_ais_indicator(r))
    high_ids = [r["id"] for r in dossier["records"]
                if r["classification"] == "high_priority"]
    silent_id = next(r["id"] for r in dossier["ais_indicator_suppressed"]
                     if not r["potential_indicators"])

    def pos(r):
        return f"{r['position']['lat']}, {r['position']['lon']}"

    # The validator is fed the exact failures observed in real model output.
    bad_report = {
        "executive_summary": (
            f"All vessels are dark. An additional dark vessel ({silent_id}) "
            f"was detected inside the active closure."),
        "inspection_briefs": [
            {"id": matched_c["id"], "priority": "medium",
             "position": pos(matched_c),
             "indicators": ["not broadcasting AIS as required"],
             "regulation_concerned": "Article 10(1), Council Regulation (EC) "
                                     "No 1224/2009",
             "suggested_action": "board and verify AIS carriage",
             "caveat": "the master may switch off AIS for crew safety"},
            {"id": dark_c["id"], "priority": "high",
             "position": "40.0, -3.7",
             "indicators": [],
             "regulation_concerned": "none identified",
             "suggested_action": "board",
             "caveat": "AIS technical failure"},
        ],
        "methodological_note": "single snapshot",
        "human_decision_required": "whether to dispatch",
    }
    bad = validate.validate_report(dossier, bad_report)
    msgs = [m for _, _, m in bad]

    results.append(check(
        any("vessel is broadcasting" in m and "regulation cited" in m
            for m in msgs),
        "flags the AIS carriage requirement cited against a broadcasting vessel"))
    results.append(check(
        any("indicators list" in m for m in msgs),
        "flags AIS invoked in the indicators field of a broadcasting vessel"))
    results.append(check(
        any("suggested action" in m for m in msgs),
        "flags AIS invoked in the suggested action of a broadcasting vessel"))
    results.append(check(
        any("coordinates must never be altered" in m for m in msgs),
        "flags a brief whose position does not match the dossier"))
    results.append(check(
        any("no inspection brief" in m for m in msgs),
        f"flags a high-priority record without a brief (high: {high_ids})"))
    results.append(check(
        any("appears in the narrative" in m for m in msgs),
        "flags a silently-suppressed vessel reintroduced in the narrative"))
    results.append(check(
        any("no regulation is named" in m for m in msgs),
        "flags a record with indicators but no regulation named"))
    results.append(check(
        validate.has_blockers(bad),
        "classifies these as blocking issues"))

    # 19. Multilingual: the same violation written in Spanish is caught.
    spanish_report = {
        "executive_summary": "Resumen de la escena.",
        "inspection_briefs": [
            {"id": matched_c["id"], "priority": "high",
             "position": pos(matched_c),
             "indicators": ["arte de fondo prohibido en la zona"],
             "regulation_concerned": "Artículo 10, Reglamento (CE) "
                                     "nº 1224/2009",
             "suggested_action": "inspección en puerto",
             "caveat": "posible tránsito"},
        ],
        "methodological_note": "instantánea única",
        "human_decision_required": "si se despacha patrulla",
    }
    spanish = validate.validate_report(dossier, spanish_report)
    results.append(check(
        any(sev == validate.BLOCKER and w == f"brief {matched_c['id']}"
            and "carriage requirement" in m for sev, w, m in spanish),
        "catches the AIS requirement cited in Spanish against a broadcasting "
        "vessel"))

    # 20. A clean report over the same dossier produces no issues at all.
    def clean_caveat(r):
        if r["ais"] == "matched":
            return ("the vessel may be in lawful transit; registry gear "
                    "information may be outdated")
        if has_ais_indicator(r):
            return ("lawful derogation possible: check whether an AIS "
                    "switch-off notification was filed for this time window "
                    "(Art. 10(2))")
        return ("below the AIS carriage threshold: absence of a broadcast is "
                "not an indicator; radar-based activity inference may be wrong")

    clean_report = {
        "executive_summary": "Seven inspection candidates identified, three "
                             "of them high priority.",
        "inspection_briefs": [
            {"id": r["id"], "position": pos(r),
             "priority": "high" if r["classification"] == "high_priority"
                         else "medium",
             "indicators": [i["reason"] for i in r["potential_indicators"]],
             "regulation_concerned": "; ".join(
                 i["reason"] for i in r["potential_indicators"]),
             "suggested_action": (f"board and verify; "
                                  f"{r.get('distance_from_base_km', '?')} km "
                                  f"from base"),
             "caveat": clean_caveat(r)}
            for r in dossier["inspection_candidates"]
        ],
        "methodological_note": "single snapshot",
        "human_decision_required": "whether to dispatch",
    }
    clean = validate.validate_report(dossier, clean_report)
    results.append(check(
        not clean,
        f"passes a well-formed report with no false alarms ({clean})"))

    print("\nOutput validation: analyst prioritisation")

    bad_prioritisation = {
        "prioritised_candidates": [
            {"id": "D-999", "rank": 1},
            {"id": "D-012", "rank": 2},  # exists, but not a candidate
        ],
        "observed_pattern": f"suspicious activity near {silent_id}",
        "overall_recommendation": "dispatch",
    }
    pri = validate.validate_prioritisation(dossier, bad_prioritisation)
    pri_msgs = [m for _, _, m in pri]
    results.append(check(
        any("does not exist" in m for m in pri_msgs),
        "flags a prioritised id that does not exist in the dossier"))
    results.append(check(
        any("not an inspection candidate" in m for m in pri_msgs),
        "flags a prioritised id that is not an inspection candidate"))
    results.append(check(
        any("analyst narrative" in w for _, w, _ in pri),
        "flags a silently-suppressed vessel in the analyst narrative"))
    results.append(check(
        validate.has_blockers(pri),
        "classifies analyst violations as blocking issues"))

    good_prioritisation = {
        "prioritised_candidates": [
            {"id": r["id"], "rank": i + 1}
            for i, r in enumerate(dossier["inspection_candidates"])],
        "observed_pattern": ("clustering in MPA-01 and RES-03; D-005 is "
                             "flagged on zone indicators only"),
        "overall_recommendation": "dispatch to RES-03 first",
    }
    results.append(check(
        not validate.validate_prioritisation(dossier, good_prioritisation),
        "passes a clean prioritisation that mentions D-005 (a legitimate "
        "candidate) without false alarms"))

    passed = sum(results)
    print(f"\n{passed}/{len(results)} checks passed\n")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
