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

try:
    import agents
except ImportError:                     # noqa: S110
    # Deferred: these checks run on a bare interpreter. Only the
    # analyst-omission section needs agents, which pulls in the OpenAI SDK.
    agents = None

import analysis
import data
import environment
import geo
import validate

def citation_for(record: dict) -> str:
    """A regulation citation that fits this record's own indicators.

    The regulation field names the provisions at stake; it does not restate the
    indicators, which validate.py reports as a defect in its own right. This
    stays AIS-free for a zone-only vessel and names the carriage rule only where
    the record actually engages it.
    """
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

def check(condition: bool, description: str) -> bool:
    print(f"  {'PASS' if condition else 'FAIL'}  {description}")
    return bool(condition)


def det(det_id, lat, lon, length, ais_matched: "bool | None" = False,
        fishing=0.0, gear="unknown", **extra) -> dict:
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
             "regulation_concerned": citation_for(r),
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

    print("\nNarrative priority claims")

    # An analyst run stated "three high-priority vessels (D-010, D-004, D-005)"
    # while D-005 was medium. The claim is only checked inside a parenthesised
    # list, so looser phrasings must not produce false alarms.
    high = next(r for r in dossier["records"]
                if r["classification"] == "high_priority")
    medium = next(r for r in dossier["records"]
                  if r["classification"] == "medium_priority")

    misattributed = {
        "prioritised_candidates": [],
        "observed_pattern": (f"three high-priority vessels ({high['id']}, "
                             f"{medium['id']}) cluster near the base"),
        "overall_recommendation": "",
        "excluded_by_caution": [],
        "limitations": [],
    }
    flagged = validate.validate_prioritisation(dossier, misattributed)
    results.append(check(
        any(medium["id"] in m and "narrative lists it among" in m
            for _, _, m in flagged),
        f"flags {medium['id']} ({medium['classification']}) claimed as high-priority"))

    faithful = {
        "prioritised_candidates": [],
        "observed_pattern": (f"high-priority vessels ({high['id']}) lie nearest "
                             f"the base; inspect {medium['id']} as follow-up"),
        "overall_recommendation": "",
        "excluded_by_caution": [],
        "limitations": [],
    }
    results.append(check(
        not [i for i in validate.validate_prioritisation(dossier, faithful)
             if "narrative lists it among" in i[2]],
        "does not flag a correct claim that merely mentions a medium record nearby"))

    print("\nRegressions caught in real runs")

    high = next(r for r in dossier["records"]
                if r["classification"] == "high_priority")
    medium = next(r for r in dossier["records"]
                  if r["classification"] == "medium_priority")

    def brief_for(record, **overrides):
        base = {
            "id": record["id"],
            "priority": record["classification"].replace("_priority", ""),
            "position": (f"{record['position']['lat']}, "
                         f"{record['position']['lon']}"),
            "indicators": [i["reason"] for i in record["potential_indicators"]],
            "regulation_concerned": record["potential_indicators"][0]["reason"][:50],
            "suggested_action": "Board and verify gear and documentation",
            "caveat": "The gear inference may be wrong",
        }
        base.update(overrides)
        return base

    # An empty regulation string slipped through: the earlier rule only looked
    # for the words "none identified", so "" matched nothing.
    empty_reg = {
        "executive_summary": "Candidates identified.",
        "inspection_briefs": [brief_for(high, regulation_concerned=""),
                              brief_for(medium)],
        "methodological_note": "n/a", "human_decision_required": "n/a",
    }
    results.append(check(
        any("no regulation is named" in m
            for _, _, m in validate.validate_report(dossier, empty_reg)),
        "flags an empty regulation field, not just the words 'none identified'"))

    # A writer run reduced the action to a distance.
    distance_action = {
        "executive_summary": "Candidates identified.",
        "inspection_briefs": [brief_for(high, suggested_action="40.77 km from base"),
                              brief_for(medium)],
        "methodological_note": "n/a", "human_decision_required": "n/a",
    }
    results.append(check(
        any("states context rather than an instruction" in m
            for _, _, m in validate.validate_report(dossier, distance_action)),
        "flags a suggested action that is only a distance"))

    # The misattribution also occurs without parentheses.
    bare_claim = {
        "prioritised_candidates": [],
        "observed_pattern": (f"High-priority detections {high['id']}, "
                             f"{medium['id']} form a tight cluster"),
        "overall_recommendation": "",
        "excluded_by_caution": [], "limitations": [],
    }
    flagged = validate.validate_prioritisation(dossier, bare_claim)
    results.append(check(
        any(medium["id"] in m and "narrative lists it among" in m
            for _, _, m in flagged)
        and not any(high["id"] in m and "narrative lists it among" in m
                    for _, _, m in flagged),
        "flags an unparenthesised priority claim, and only the wrong id"))

    print("\nPresence is not activity")

    # A compliant vessel: AIS on, registry gear aboard, crossing an integral
    # reserve at transit speed with the activity classifier at 0.05. An earlier
    # version raised "apparent fishing activity" for it, because the registry
    # gear class alone satisfied the branch. Registry gear says what a vessel is
    # licensed for, not what it is doing.
    reserve = next(z for z in zones_doc["zones"]
                   if "all" in z.get("prohibited_gear", []))
    inside = geo.centroid(reserve["polygon"])
    transiting = analysis.assess_detection(
        det("T-TRANSIT", inside[0], inside[1], 30.0, ais_matched=True,
            fishing=0.05, gear="purse_seine"),
        zones_doc["zones"], config, day)
    results.append(check(
        not transiting["potential_indicators"] and transiting["score"] == 0,
        f"a compliant vessel in transit through an integral reserve raises no "
        f"indicator (got {len(transiting['potential_indicators'])})"))

    # The same position with the classifier above threshold must still be caught.
    fishing_there = analysis.assess_detection(
        det("T-FISHING", inside[0], inside[1], 30.0, ais_matched=True,
            fishing=0.95, gear="purse_seine"),
        zones_doc["zones"], config, day)
    results.append(check(
        bool(fishing_there["potential_indicators"]),
        "apparent fishing in the same reserve is still an indicator"))

    print("\nNo double counting")

    # The corroboration item must not be awarded when an indicator already rests
    # on the activity classifier: that is one observation counted twice, and it
    # previously decided a classification.
    corroboration = [b for b in fishing_there["score_breakdown"]
                     if "corroboration" in b["factor"]]
    results.append(check(
        not corroboration,
        f"no corroboration points where an indicator already rests on the "
        f"activity classifier (got {corroboration})"))

    print("\nFail loudly on decisive missing fields")

    missing_activity = det("T-NOFS", 36.3, -7.4, 30.0)
    missing_activity.pop("fishing_score")
    try:
        analysis.assess_detection(missing_activity, zones_doc["zones"], config, day)
        raised = False
    except ValueError as exc:
        raised = "fishing_score" in str(exc)
    results.append(check(
        raised,
        "a missing fishing_score raises instead of silently meaning 'not fishing'"))

    print("\nValidator: language and omissions")

    # Fidelity must hold in the authority's working language, not only in
    # English. The earlier version of this test asserted that a Spanish report
    # raised no alarm — which it did, because the check was switched off for
    # Spanish. That verified the absence of a check, not a check. These two
    # verify the check itself, in both directions.
    spanish_dossier = dict(dossier)
    spanish_dossier["output_language"] = "Spanish"
    candidates = spanish_dossier["inspection_candidates"]

    def build_spanish_brief(indicators_for):
        return {
            "executive_summary": "Se han identificado candidatos a inspeccion.",
            "inspection_briefs": [
                {"id": r["id"],
                 "priority": r["classification"].replace("_priority", ""),
                 "position": (f"{r['position']['lat']}, {r['position']['lon']}"),
                 "indicators": indicators_for(r),
                 "regulation_concerned": citation_for(r),
                 "suggested_action": "Proceder a la posicion e inspeccionar el arte",
                 "caveat": "El buque podria estar en transito sin faenar"}
                for r in candidates],
            "methodological_note": "n/a", "human_decision_required": "n/a",
        }

    def fidelity_alarms(report):
        return [i for i in validate.validate_report(spanish_dossier, report)
                if "cite none of" in i[2]]

    fabricated = build_spanish_brief(
        lambda r: ["el buque presenta danos estructurales visibles en el casco"])
    results.append(check(
        len(fidelity_alarms(fabricated)) >= len(candidates),
        f"fabricated Spanish indicators are caught "
        f"({len(fidelity_alarms(fabricated))} of {len(candidates)} briefs)"))

    def faithful_translation(record):
        tokens = sorted(validate._invariant_tokens(" ".join(
            i["reason"] for i in record["potential_indicators"])))
        return ["eslora estimada por radar e indicios en zona regulada; "
                "referencias: " + ", ".join(tokens)]

    results.append(check(
        not fidelity_alarms(build_spanish_brief(faithful_translation)),
        "a faithful Spanish translation raises no fidelity alarm"))

    # The analyst must not silently drop a high-priority record either.
    high_ids = [r["id"] for r in dossier["records"]
                if r["classification"] == "high_priority"]
    partial = {"prioritised_candidates": [{"id": high_ids[0], "rank": 1}],
               "observed_pattern": "", "overall_recommendation": "",
               "excluded_by_caution": [], "limitations": []}
    omitted = validate.validate_prioritisation(dossier, partial)
    results.append(check(
        any(high_ids[1] in m and "did not prioritise" in m
            for _, _, m in omitted),
        "flags a high-priority record the analyst left out"))

    print("\nDegraded indicators do not create candidacy")

    # A length estimate that does not clear the threshold once its own +/-sigma
    # is applied yields an indicator whose text says "inconclusive". It may
    # corroborate; it must not put a vessel on the patrol route by itself.
    threshold = config["ais_length_threshold_m"]
    sigma = config.get("length_sigma_m", 0.0)
    near = threshold - 1.0          # inside the uncertainty band
    firmly = threshold + sigma + 1.0  # clear of it

    near_record = analysis.assess_detection(
        det("T-NEAR", 36.0, -8.0, near, ais_matched=False, fishing=0.1),
        zones_doc["zones"], config, day)
    results.append(check(
        near_record["potential_indicators"]
        and near_record["classification"] == "below_candidate_threshold",
        f"a {near} m estimate against a {threshold} m threshold is recorded but "
        f"not a candidate (got {near_record['classification']})"))

    firm_record = analysis.assess_detection(
        det("T-FIRM", 36.0, -8.0, firmly, ais_matched=False, fishing=0.1),
        zones_doc["zones"], config, day)
    results.append(check(
        firm_record["classification"] == "medium_priority",
        f"a {firmly} m estimate, clear of the uncertainty band, is a candidate "
        f"(got {firm_record['classification']})"))

    # And the record must not reach the patrol route either.
    results.append(check(
        all(r["classification"] != "below_candidate_threshold"
            for r in dossier["inspection_candidates"]),
        "no below-threshold record appears among inspection candidates"))

    print("\nBriefs may not add indicators the record does not contain")

    # Rule 6c bounds substitution: a brief that replaces the record's content is
    # caught because it carries none of the record's anchors. It does not bound
    # addition. A brief that reproduces both indicators faithfully and appends a
    # third, invented one keeps every anchor and satisfied 6c completely — in
    # English and in Spanish alike. Addition is the likelier failure, and an
    # added line in an inspection brief is an accusation nobody observed.
    two_indicator = next(r for r in dossier["inspection_candidates"]
                         if len(r["potential_indicators"]) == 2)

    def brief_with(record, indicators):
        return {
            "id": record["id"],
            "priority": record["classification"].replace("_priority", ""),
            "position": (f"{record['position']['lat']}, "
                         f"{record['position']['lon']}"),
            "indicators": indicators,
            "regulation_concerned":
                record["potential_indicators"][0]["reason"][:60],
            "suggested_action": "Board and verify gear and documentation",
            "caveat": "The gear inference may be wrong",
        }

    def issues_for(record, indicators):
        report = {
            "executive_summary": "Candidates identified.",
            "inspection_briefs": [brief_with(record, indicators)],
            "methodological_note": "n/a", "human_decision_required": "n/a",
        }
        return [i for i in validate.validate_report(dossier, report)
                if record["id"] in i[1]]

    faithful = [i["reason"] for i in two_indicator["potential_indicators"]]
    invented = ("vessel seen deploying prohibited driftnets with undeclared "
                "protected species aboard")

    added = issues_for(two_indicator, faithful + [invented])
    results.append(check(
        any(sev == validate.BLOCKER and "added an indicator" in msg
            for sev, _, msg in added),
        f"a faithful brief with one appended invented indicator is blocked "
        f"({len(faithful)} in record, {len(faithful) + 1} in brief)"))

    # Consolidating two record indicators into one well-formed statement is
    # legitimate reporting, not invention. Only an excess is a failure.
    consolidated = issues_for(two_indicator, [" ".join(faithful)])
    results.append(check(
        not any("added an indicator" in msg for _, _, msg in consolidated),
        "consolidating two indicators into one raises no addition issue"))

    # Fabricated indicator text sits in the field an inspector reads first, and
    # every neighbouring rule blocks. On a faithful translation this check
    # measures zero, so the false-positive risk that justified a warning is gone.
    substituted = issues_for(two_indicator,
                             ["una observacion que no consta en el expediente"])
    results.append(check(
        any(sev == validate.BLOCKER and "cite none of" in msg
            for sev, _, msg in substituted),
        "a brief citing none of the record's anchors is a blocker, not a warning"))

    print("\nNarrative claims and analyst omissions, at real sentence length")

    high_rec = next(r for r in dossier["records"]
                    if r["classification"] == "high_priority")
    med_rec = next(r for r in dossier["records"]
                   if r["classification"] == "medium_priority")
    records_by_id = {r["id"]: r for r in dossier["records"]}

    # Real sentences put words between the claim and the list. An earlier window
    # of 40 characters missed this one at 56.
    long_claim = (f"High-priority detections cluster west of the patrol base, "
                  f"with three vessels ({high_rec['id']}, {med_rec['id']}) "
                  f"showing possible activity inside the reserve")
    flagged = validate._misattributed_priorities(long_claim, records_by_id)
    results.append(check(
        any(med_rec["id"] in p for p in flagged)
        and not any(high_rec["id"] in p for p in flagged),
        "a priority claim separated from its list by a clause is caught, and "
        "only the wrong id is named"))

    # But the window must not run past a second priority term: there the list
    # belongs to the later claim.
    two_claims = (f"Inspect the high-priority candidates first, then the "
                  f"medium-priority ones ({med_rec['id']}).")
    results.append(check(
        not validate._misattributed_priorities(two_claims, records_by_id),
        "a list belonging to a second priority claim is not attributed to the "
        "first"))

    # The analyst must not silently shorten the candidate list either.
    without_medium = {
        "prioritised_candidates": [
            {"id": r["id"], "rank": i + 1}
            for i, r in enumerate(dossier["inspection_candidates"])
            if r["id"] != med_rec["id"]],
        "observed_pattern": "", "overall_recommendation": "",
        "excluded_by_caution": [], "limitations": [],
    }
    results.append(check(
        any(med_rec["id"] in m and "did not prioritise" in m
            for _, _, m in validate.validate_prioritisation(
                dossier, without_medium)),
        f"a medium-priority record dropped by the analyst is reported "
        f"({med_rec['id']})"))

    # --- Fixed-infrastructure false-positive guard (Task 4.1) ---
    print("\nFixed-infrastructure suppression: both directions of caution")
    platform = {"id": "FIX-T", "name": "Test platform", "type": "fixed_platform",
                "lat": 36.70, "lon": -7.05, "match_radius_m": 400}

    # A dark 30 m return on the platform, inside an MPA, with a high activity
    # score: without the guard this is a strong candidate. It must be attributed
    # to the structure and raise no candidate.
    on_structure = analysis.assess_detection(
        det("T-FIX", 36.701, -7.049, 30.0, ais_matched=False, fishing=0.9,
            gear="bottom_trawl"), zones, config, day, [platform])
    results.append(check(
        on_structure["classification"] == "fixed_structure",
        "detection on a charted structure is classified fixed_structure, not a "
        "candidate"))
    results.append(check(
        on_structure["potential_indicators"] == [] and on_structure["score"] == 0,
        "a structure-attributed detection carries no indicators and scores zero"))
    results.append(check(
        any("suppressed as attributable to charted fixed structure" in c
            for c in on_structure["contextual_notes"]),
        "the suppressed indicators are surfaced as context, not dropped silently"))
    results.append(check(
        on_structure.get("fixed_structure", {}).get("id") == "FIX-T",
        "the record names the structure it was attributed to"))

    # Under-reporting guard: an identical dark vessel AWAY from any structure is
    # still assessed normally — the guard must not swallow real vessels.
    off_structure = analysis.assess_detection(
        det("T-FIX2", 36.62, -7.15, 30.0, ais_matched=False, fishing=0.9,
            gear="bottom_trawl"), zones, config, day, [platform])
    results.append(check(
        off_structure["classification"] in analysis.CANDIDATE_CLASSES,
        "an identical dark vessel away from the structure remains a candidate"))
    results.append(check(
        analysis.assess_detection(
            det("T-FIX3", 36.62, -7.15, 30.0, ais_matched=False, fishing=0.9,
                gear="bottom_trawl"), zones, config, day, [])["classification"]
        == off_structure["classification"],
        "an empty registry leaves classification unchanged (default: no guard)"))

    print("\nEnvironmental gate: season before moon, and no reach into scores")

    # The angula campaign is regulatory, and it is the filter anyone in the
    # sector applies before looking at the moon at all. An earlier version
    # modelled the moon correctly and ignored the season, so a July new moon —
    # months after the fishery closes — was reported as peak conditions.
    winter = {"environment": {"season": {"start": "11-01", "end": "02-28"}}}

    in_season = environment.angula_conditions("2024-01-11T02:00:00Z", winter)
    results.append(check(
        in_season["suitability"] == environment.HIGH and in_season["in_season"],
        f"a dark spring-tide night inside the campaign is high "
        f"(got {in_season['suitability']})"))

    # Same lunar geometry, six months later: new moon, spring tides, closed
    # fishery. The moon figures stay true; the label must not say high.
    out_of_season = environment.angula_conditions("2024-07-05T22:00:00Z", winter)
    results.append(check(
        out_of_season["suitability"] == environment.OUT_OF_SEASON
        and out_of_season["moon_illumination"] < 0.1,
        f"the same lunar conditions out of season are not high, while the moon "
        f"figures remain computed (got {out_of_season['suitability']}, "
        f"illumination {out_of_season['moon_illumination']})"))

    # A November-to-February window wraps the year boundary, so a naive
    # start <= today <= end excludes December and January: most of the season.
    december = environment.angula_conditions("2024-12-20T02:00:00Z", winter)
    february = environment.angula_conditions("2025-02-15T02:00:00Z", winter)
    september = environment.angula_conditions("2024-09-15T02:00:00Z", winter)
    results.append(check(
        december["in_season"] and february["in_season"]
        and not september["in_season"],
        f"a window crossing the year boundary holds on both sides "
        f"(Dec {december['in_season']}, Feb {february['in_season']}, "
        f"Sep {september['in_season']})"))

    # The published campaigns run to 31 March, so March is inside the window,
    # and a window whose end is a real month end contains a leap day. An earlier
    # default ended on 28 February and called both of those closed: 29 February
    # fell outside a window that contained 27 February, and the whole tail of the
    # campaign was reported as out of season.
    default_season = environment._DEFAULT_SEASON
    march = environment.angula_conditions("2026-03-15T02:00:00Z", {})
    leap_day = environment.angula_conditions("2028-02-29T02:00:00Z", {})
    results.append(check(
        march["in_season"] and leap_day["in_season"],
        f"March and a leap day fall inside the default campaign window "
        f"({default_season['start']} to {default_season['end']}): "
        f"Mar {march['in_season']}, 29 Feb {leap_day['in_season']}"))
    
    # A season bound that cannot be read must fail loudly, like every other
    # decisive piece of configuration in the engine.
    try:
        environment.angula_conditions(
            "2024-01-11T02:00:00Z",
            {"environment": {"season": {"start": "13-45", "end": "02-28"}}})
        season_raises = False
    except ValueError:
        season_raises = True
    results.append(check(
        season_raises, "an invalid season bound raises instead of being ignored"))

    # The gate ranks scanning priority. It must never reach into a vessel's
    # score: a dark spring-tide night in season is not evidence against any
    # individual boat. Moving the window swings the label from out_of_season to
    # high; every score must be unmoved by it.
    baseline = {r["id"]: (r["score"], r["classification"])
                for r in dossier["records"]}
    swung = []
    for window in ({"start": "11-01", "end": "02-28"},
                   {"start": "01-01", "end": "12-31"}):
        altered = copy.deepcopy(zones_doc)
        altered["config"].setdefault("environment", {})["season"] = window
        result = analysis.analyse(altered, detections_doc)
        swung.append(result["environmental_context"]["suitability"])
        moved = {r["id"]: (r["score"], r["classification"])
                 for r in result["records"]}
        if moved != baseline:
            swung.append("SCORES MOVED")
    results.append(check(
        "SCORES MOVED" not in swung and len(set(swung)) > 1,
        f"the suitability label swings ({' -> '.join(swung)}) without moving "
        f"any vessel score"))

    print("\nCaveat and action integrity")

    caveat_record = next(r for r in dossier["inspection_candidates"]
                         if r["estimated_length_m"]
                         >= config["ais_length_threshold_m"])

    def caveat_brief(**overrides):
        base = {
            "id": caveat_record["id"],
            "priority": caveat_record["classification"].replace("_priority", ""),
            "position": (f"{caveat_record['position']['lat']}, "
                         f"{caveat_record['position']['lon']}"),
            "indicators": [i["reason"]
                           for i in caveat_record["potential_indicators"]],
            "regulation_concerned": citation_for(caveat_record),
            "suggested_action": "Board and verify gear and documentation",
            "caveat": "The vessel may be transiting without deploying gear",
        }
        base.update(overrides)
        return base

    def caveat_issues(**overrides):
        """Issues raised against this brief only.

        A report carrying one brief also raises omission issues for every other
        candidate; those belong to a different rule and would mask what is being
        tested here.
        """
        report = {"executive_summary": "Candidates identified.",
                  "inspection_briefs": [caveat_brief(**overrides)],
                  "methodological_note": "n/a", "human_decision_required": "n/a"}
        return [i for i in validate.validate_report(dossier, report)
                if caveat_record["id"] in i[1] and "no inspection brief" not in i[2]]

    # The caveat is the counter-hypothesis an inspector must rule out. A brief
    # that raises indicators and offers none is unbalanced by omission.
    results.append(check(
        any("mandatory caveat is missing" in message
            for _, _, message in caveat_issues(caveat="")),
        "a brief with indicators but no caveat is blocked"))

    # A caveat that contradicts its own record would have an inspector dismiss
    # a live indicator. The threshold is read from the dossier, so the rule
    # follows a jurisdiction that sets its own.
    caveat_threshold = int(config["ais_length_threshold_m"])
    results.append(check(
        any("threshold, but the record" in message for _, _, message
            in caveat_issues(caveat=f"The vessel is below {caveat_threshold} m, "
                                    f"so AIS carriage is not required")),
        f"a caveat claiming the vessel is under {caveat_threshold} m is blocked "
        f"when the record gives {caveat_record['estimated_length_m']} m"))

    # The system proposes inspection; it does not order seizure. An action
    # beyond the inspector's authority is outside the system's remit.
    results.append(check(
        any("exceeds inspector authority" in message for _, _, message
            in caveat_issues(suggested_action="Seize the vessel and arrest the "
                                              "master immediately")),
        "an action invoking seizure or arrest is blocked"))

    results.append(check(
        not caveat_issues(),
        f"a well-formed brief raises none of these ({caveat_issues()})"))

    print("\nSuggested action: instruction, not distance")

    action_record = dossier["inspection_candidates"][0]

    def action_issues(action):
        brief = {
            "id": action_record["id"],
            "priority": action_record["classification"].replace("_priority", ""),
            "position": (f"{action_record['position']['lat']}, "
                         f"{action_record['position']['lon']}"),
            "indicators": [i["reason"]
                           for i in action_record["potential_indicators"]],
            "regulation_concerned": citation_for(action_record),
            "suggested_action": action,
            "caveat": "The vessel may be transiting without deploying gear",
        }
        report = {"executive_summary": "Candidates identified.",
                  "inspection_briefs": [brief],
                  "methodological_note": "n/a", "human_decision_required": "n/a"}
        return [i for i in validate.validate_report(dossier, report)
                if "states context" in i[2]]

    # The rule asks whether an instruction remains once the distance is set
    # aside, not whether the action opens with one. An earlier version matched
    # any action STARTING with a distance and flagged every brief in a correct
    # report, because the model wrote the range in front of a real instruction.
    results.append(check(
        not action_issues("38.0 km from base: board and verify AIS compliance, "
                          "gear and documentation."),
        "an instruction preceded by the range is accepted"))

    results.append(check(
        not action_issues("Board and verify gear and documentation; "
                          "38.0 km from base"),
        "an instruction followed by the range is accepted"))

    # But an action that is only context still has nothing an inspector can do.
    results.append(check(
        bool(action_issues("38.0 km from base")),
        "an action that is only a distance is reported"))

    results.append(check(
        bool(action_issues("Inspect")),
        "an action too short to act on is reported"))

    print("\nAnalyst omission: detected before the report is written")

    if agents is None:
        print("  SKIP  analyst-omission checks: the OpenAI SDK is not installed. "
              "Everything else here runs without it.")
    else:
        # The observed failure is truncation, not invention: the analyst ranks the
        # obvious candidates and stops. agents.prioritise retries once with the
        # dropped ids fed back, so this helper is what decides whether that happens.
        candidate_ids = [r["id"] for r in dossier["inspection_candidates"]]

        complete_ranking = {"prioritised_candidates":
                            [{"id": i} for i in candidate_ids]}
        results.append(check(
            not agents._omitted_candidates(dossier, complete_ranking),
            f"a ranking covering all {len(candidate_ids)} candidates reports no omission"))

        truncated = {"prioritised_candidates":
                     [{"id": i} for i in candidate_ids[:len(candidate_ids) // 2]]}
        results.append(check(
            set(agents._omitted_candidates(dossier, truncated))
            == set(candidate_ids[len(candidate_ids) // 2:]),
            "a truncated ranking names exactly the candidates it dropped"))

        results.append(check(
            len(agents._omitted_candidates(dossier, {})) == len(candidate_ids),
            "a response with no ranking at all reports every candidate as omitted"))

    passed = sum(results)
    print(f"\n{passed}/{len(results)} checks passed\n")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())