"""Orchestrator.

Pipeline:
    detections + regulatory layer
        -> deterministic cross-reference (tool)
        -> analyst agent   (Nemotron)   -> validated in code
        -> writer agent    (Nemotron)   -> validated in code
        -> inspection briefs

Validation gates the output: if either agent's output contains blocking
issues, the briefs are withheld, only the issue summary is printed, and the
process exits non-zero. A report with blocking issues is never shown as if it
were fit for an inspector.

Usage:
    python src/main.py --cross-reference-only     # no API key needed
    python src/main.py                            # full pipeline
"""

import argparse
import json
import sys

import analysis
import data
import validate

# Deferred availability, module-level import: --cross-reference-only works
# without the SDK installed, and `import main` never hits a NameError.
try:
    import agents
except ImportError:
    agents = None


def banner(title: str) -> None:
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


def print_dossier(dossier: dict) -> None:
    banner(f"FACTUAL DOSSIER - {dossier['study_area']} - scene {dossier['scene']['timestamp']}")
    print(f"Detections analysed: {dossier['total_detections']}")
    print(f"AIS carriage threshold applied: {dossier['ais_length_threshold_m']} m "
          f"(length uncertainty +/-{dossier['length_sigma_m']} m)")
    for closure in dossier["active_closures"]:
        print(f"Active closure: {closure['zone']} ({closure['reason']})")
    if dossier.get("patrol_base"):
        print(f"Patrol base: {dossier['patrol_base']['name']} "
              f"(radius {dossier['patrol_radius_km']} km)")

    print("\nClassification summary:")
    for label, count in dossier["classification_summary"].items():
        print(f"  {label:<18} {count}")

    print("\n--- INSPECTION CANDIDATES ---")
    for record in dossier["inspection_candidates"]:
        identity = ""
        if "identity" in record and record["identity"].get("name"):
            identity = f" [{record['identity']['name']} / {record['identity']['flag']}]"
        n = len(record["potential_indicators"])
        distance = ""
        if "distance_from_base_km" in record:
            distance = f" | {record['distance_from_base_km']} km from base"
        print(f"\n  {record['id']}{identity}  -> {record['classification'].upper()} "
              f"| {n} independent indicator(s) concur{distance}")
        print(f"    Pos {record['position']['lat']}, {record['position']['lon']} | "
              f"length {record['estimated_length_m']} m | AIS: {record['ais']} | "
              f"likely gear: {record['likely_gear']}")
        for zone in record["zones"]:
            print(f"    Zone: {zone['name']} ({zone['type']})")
        for indicator in record["potential_indicators"]:
            print(f"    Indicator: {indicator['reason']}")
        for note in record.get("contextual_notes", []):
            print(f"    Context (not an indicator): {note}")
        if record.get("ais_note"):
            print(f"    AIS note: {record['ais_note']}")
        for item in record["score_breakdown"]:
            print(f"      +{item['points']:<3} {item['factor']}")

    if dossier.get("patrol_sequence"):
        print("\n--- PATROL SEQUENCE (priority, then distance from base) ---")
        for stop in dossier["patrol_sequence"]:
            print(f"  {stop['id']}  {stop['priority']:<15} "
                  f"{stop['distance_from_base_km']:>7} km  "
                  f"({stop['position']['lat']}, {stop['position']['lon']})")

    others = [r for r in dossier.get("records", [])
              if not r["classification"].endswith("_priority")
              and r["id"] not in {x["id"] for x in
                                  dossier.get("ais_indicator_suppressed", [])}]
    if others:
        # Printed rather than dropped: a record can carry an indicator that
        # cites a legal provision and still fall below the candidate threshold.
        # Reporting only what we act on would hide that from the reader.
        print("\n--- BELOW CANDIDATE THRESHOLD (listed, not actioned) ---")
        for record in others:
            reasons = [i["reason"] for i in record.get("potential_indicators", [])]
            summary = reasons[0][:90] + "..." if reasons else "no indicators"
            print(f"  {record['id']} ({record['classification']}, "
                  f"score {record['score']}): {summary}")

    print("\n--- AIS INDICATOR SUPPRESSED (duty of caution) ---")
    for record in dossier["ais_indicator_suppressed"]:
        print(f"  {record['id']} ({record['classification']}): {record['ais_note']}")


def print_prioritisation(prioritisation: dict) -> None:
    banner("ANALYST AGENT - PRIORITISATION")
    for candidate in prioritisation.get("prioritised_candidates", []):
        print(f"  {candidate.get('rank')}. {candidate.get('id')} "
              f"[{candidate.get('indicator_type')}, "
              f"confidence {candidate.get('confidence')}]")
        print(f"     {candidate.get('reason')}")
    print("\nAIS not applicable (indicator suppressed):")
    for item in prioritisation.get("ais_not_applicable", []):
        print(f"  - {item}")
    print(f"\nObserved pattern: {prioritisation.get('observed_pattern', 'n/a')}")
    print(f"Recommendation:   {prioritisation.get('overall_recommendation', 'n/a')}")
    if prioritisation.get("limitations"):
        print("\nStated limitations:")
        for limitation in prioritisation["limitations"]:
            print(f"  - {limitation}")


def print_briefs(report: dict) -> None:
    banner("EXECUTIVE SUMMARY")
    print(report.get("executive_summary", ""))

    banner("INSPECTION BRIEFS")
    for brief in report.get("inspection_briefs", []):
        # Models return position either as "lat, lon" or as {"lat":..,"lon":..}.
        position = brief.get("position")
        if isinstance(position, dict):
            position = f"{position.get('lat')}, {position.get('lon')}"
        print(f"\n  [{str(brief.get('priority', '')).upper()}] "
              f"{brief.get('id')} - {position}")
        for indicator in brief.get("indicators", []):
            print(f"    - {indicator}")
        print(f"    Regulation: {brief.get('regulation_concerned')}")
        print(f"    Action:     {brief.get('suggested_action')}")
        print(f"    Caveat:     {brief.get('caveat')}")

    print(f"\nMethodological note: {report.get('methodological_note', '')}")
    print(f"Human decision required: {report.get('human_decision_required', '')}")


def write_last_run(dossier: dict, prioritisation, report, issues: list) -> None:
    with open("last_run.json", "w", encoding="utf-8") as f:
        json.dump({"dossier": dossier,
                   "prioritisation": prioritisation,
                   "report": report,
                   "validation": [{"severity": s_, "where": w_, "message": m_}
                                  for s_, w_, m_ in issues]},
                  f, ensure_ascii=False, indent=2)
    print("\n(Full output written to last_run.json)")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Dark vessel inspection triage")
    parser.add_argument("--cross-reference-only", action="store_true",
                        help="Run the deterministic engine only, no model calls")
    parser.add_argument("--zones", default="zones.json")
    parser.add_argument("--detections", default="detections.json")
    args = parser.parse_args()

    zones_doc = data.load_zones(args.zones)
    detections_doc = data.load_detections(args.detections)

    # --- Step 1: deterministic cross-reference (the tool) ---
    dossier = analysis.analyse(zones_doc, detections_doc)
    print_dossier(dossier)

    if args.cross_reference_only:
        return 0

    if agents is None:
        print("\n[ERROR] Could not import 'agents'. Install dependencies first:"
              "\n  pip install -r requirements.txt", file=sys.stderr)
        return 1

    # --- Step 2: analyst agent, validated before it is shown ---
    try:
        prioritisation = agents.prioritise(dossier)
    except Exception as exc:  # noqa: BLE001
        print(f"\n[ERROR] Model call failed: {exc}", file=sys.stderr)
        print("Check NVIDIA_API_KEY and the model identifier "
              "(NEMOTRON_MODEL environment variable).", file=sys.stderr)
        return 1

    prioritisation_issues = validate.validate_prioritisation(dossier, prioritisation)
    if validate.has_blockers(prioritisation_issues):
        banner("ANALYST VALIDATION")
        print(validate.format_issues(prioritisation_issues))
        print("\nBlocking issues found in the analyst output: the prioritisation "
              "is withheld and no report is issued.")
        write_last_run(dossier, prioritisation, None, prioritisation_issues)
        return 1

    print_prioritisation(prioritisation)
    if prioritisation_issues:  # warnings only
        banner("ANALYST VALIDATION")
        print(validate.format_issues(prioritisation_issues))

    # --- Step 3: writer agent, validated before it is shown ---
    try:
        report = agents.write_briefs(dossier, prioritisation)
    except Exception as exc:  # noqa: BLE001
        print(f"\n[ERROR] Model call failed: {exc}", file=sys.stderr)
        return 1

    report_issues = validate.validate_report(dossier, report)
    all_issues = prioritisation_issues + report_issues

    if validate.has_blockers(report_issues):
        banner("OUTPUT VALIDATION")
        print(validate.format_issues(report_issues))
        print("\nBlocking issues found: this report is NOT issued. The briefs "
              "are withheld; only the issue summary is shown.")
        write_last_run(dossier, prioritisation, report, all_issues)
        return 1

    print_briefs(report)
    banner("OUTPUT VALIDATION")
    print(validate.format_issues(report_issues))
    write_last_run(dossier, prioritisation, report, all_issues)
    return 0


if __name__ == "__main__":
    sys.exit(main())
