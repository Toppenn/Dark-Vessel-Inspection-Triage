"""Orchestrator.

Pipeline:
    detections + regulatory layer
        -> deterministic cross-reference (tool)
        -> analyst agent   (Nemotron)
        -> writer agent    (Nemotron)
        -> inspection briefs

Usage:
    python src/main.py --cross-reference-only     # no API key needed
    python src/main.py                            # full pipeline
"""

import argparse
import json
import sys

import analysis
import data


def banner(title: str) -> None:
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


def print_dossier(dossier: dict) -> None:
    banner(f"FACTUAL DOSSIER - {dossier['study_area']} - scene {dossier['scene']['timestamp']}")
    print(f"Detections analysed: {dossier['total_detections']}")
    print(f"AIS carriage threshold applied: {dossier['ais_length_threshold_m']} m")
    for closure in dossier["active_closures"]:
        print(f"Active closure: {closure['zone']} ({closure['reason']})")

    print("\nClassification summary:")
    for label, count in dossier["classification_summary"].items():
        print(f"  {label:<18} {count}")

    print("\n--- INSPECTION CANDIDATES ---")
    for record in dossier["inspection_candidates"]:
        identity = ""
        if "identity" in record and record["identity"].get("name"):
            identity = f" [{record['identity']['name']} / {record['identity']['flag']}]"
        print(f"\n  {record['id']}{identity}  score {record['score']} "
              f"-> {record['classification'].upper()}")
        print(f"    Pos {record['position']['lat']}, {record['position']['lon']} | "
              f"length {record['estimated_length_m']} m | AIS: {record['ais']} | "
              f"likely gear: {record['likely_gear']}")
        for zone in record["zones"]:
            print(f"    Zone: {zone['name']} ({zone['type']})")
        for indicator in record["potential_indicators"]:
            print(f"    Indicator: {indicator['reason']}")
        for item in record["score_breakdown"]:
            print(f"      +{item['points']:<3} {item['factor']}")

    print("\n--- EXCLUDED BY DUTY OF CAUTION (never prioritised) ---")
    for record in dossier["excluded_by_caution"]:
        print(f"  {record['id']}: {record['note']}")


def print_prioritisation(prioritisation: dict) -> None:
    banner("ANALYST AGENT - PRIORITISATION")
    for candidate in prioritisation.get("prioritised_candidates", []):
        print(f"  {candidate.get('rank')}. {candidate.get('id')} "
              f"[{candidate.get('indicator_type')}, "
              f"confidence {candidate.get('confidence')}]")
        print(f"     {candidate.get('reason')}")
    print("\nExcluded by caution:")
    for item in prioritisation.get("excluded_by_caution", []):
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
        print(f"\n  [{str(brief.get('priority', '')).upper()}] "
              f"{brief.get('id')} - {brief.get('position')}")
        for indicator in brief.get("indicators", []):
            print(f"    - {indicator}")
        print(f"    Regulation: {brief.get('regulation_concerned')}")
        print(f"    Action:     {brief.get('suggested_action')}")
        print(f"    Caveat:     {brief.get('caveat')}")

    print(f"\nMethodological note: {report.get('methodological_note', '')}")
    print(f"Human decision required: {report.get('human_decision_required', '')}")


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

    # --- Step 2: analyst agent ---
    try:
        prioritisation = agents.prioritise(dossier)
    except Exception as exc:  # noqa: BLE001
        print(f"\n[ERROR] Model call failed: {exc}", file=sys.stderr)
        print("Check NVIDIA_API_KEY and the model identifier "
              "(NEMOTRON_MODEL environment variable).", file=sys.stderr)
        return 1

    print_prioritisation(prioritisation)

    # --- Step 3: writer agent ---
    report = agents.write_briefs(dossier, prioritisation)
    print_briefs(report)

    with open("last_run.json", "w", encoding="utf-8") as f:
        json.dump({"dossier": dossier,
                   "prioritisation": prioritisation,
                   "report": report}, f, ensure_ascii=False, indent=2)
    print("\n(Full output written to last_run.json)")
    return 0


if __name__ == "__main__":
    # Deferred import so --cross-reference-only works without the SDK installed.
    try:
        import agents
    except ImportError:
        agents = None
    sys.exit(main())
