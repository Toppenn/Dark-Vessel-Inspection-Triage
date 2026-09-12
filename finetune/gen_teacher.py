"""Teacher generation — distil the large model's briefs, gated by the validator.

This is the step that makes the fine-tune defensible rather than fashionable.

We do NOT keep whatever the teacher produced. For each synthetic scene we run
the real agent path against a large Nemotron, then run `validate.py` over the
result exactly as `main.py` does, and keep the sample only if it carries no
blocking issue. The validator is the data curator: the same executable rules
that decide whether a report reaches an inspector decide whether a sample
reaches the training set.

Two consequences worth stating in the write-up:

  * The corpus cannot contain a brief that cites the AIS carriage requirement
    against a broadcasting vessel, or moves a coordinate, or drops a
    high-priority record — because those are precisely the things the validator
    blocks. The failure modes we are trying to remove from the small model are
    absent from its supervision by construction.
  * The teacher's *rejection rate* is itself a result. "The 120B model needed
    N attempts per clean scene" is a measurement of the problem the guardrail
    exists to solve, on real outputs, not on mutations.

Usage (teacher on a local vLLM server; see sbatch_vllm_teacher.sh):

    export NVIDIA_BASE_URL=http://$TEACHER_HOST:8000/v1
    export NVIDIA_API_KEY=local
    python finetune/gen_teacher.py \
        --scenes data/scenes.jsonl \
        --out data/sft_raw.jsonl \
        --model nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-BF16 \
        --attempts 3 --workers 8
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))


def _load_agents(model: str, base_url: str | None):
    """agents.py reads its configuration from the environment at import time."""
    if base_url:
        os.environ["NVIDIA_BASE_URL"] = base_url
    os.environ["NEMOTRON_MODEL"] = model
    os.environ["ANALYST_MODEL"] = model
    os.environ["WRITER_MODEL"] = model
    os.environ.setdefault("NVIDIA_API_KEY", "local")
    import agents
    return agents


def _severity(issues: list, validate_mod) -> str:
    if validate_mod.has_blockers(issues):
        return "blocker"
    return "warning" if issues else "clean"


def process_scene(scene: dict, agents, analysis, validate, args, stats,
                  lock) -> list:
    dossier = analysis.analyse(scene["zones_doc"], scene["detections_doc"])
    rows = []

    prioritisation = None
    prio_issues: list = []
    for attempt in range(args.attempts):
        try:
            candidate = agents.prioritise(dossier)
        except Exception as exc:  # noqa: BLE001
            with lock:
                stats["analyst_error"] += 1
                stats["last_error"] = f"{type(exc).__name__}: {exc}"
            continue
        issues = validate.validate_prioritisation(dossier, candidate)
        sev = _severity(issues, validate)
        with lock:
            stats[f"analyst_{sev}"] += 1
            stats["analyst_attempts"] += 1
        if sev == "clean" or (sev == "warning" and not args.strict):
            prioritisation, prio_issues = candidate, issues
            break

    if prioritisation is None:
        with lock:
            stats["scene_dropped_analyst"] += 1
        return rows

    rows.append({
        "agent": "analyst",
        "seed": scene["seed"],
        "messages": [
            {"role": "system", "content": agents.ANALYST_SYSTEM},
            {"role": "user", "content": _analyst_user(agents, dossier)},
            {"role": "assistant",
             "content": json.dumps(prioritisation, ensure_ascii=False, indent=2)},
        ],
        "meta": {"issues": len(prio_issues),
                 "language": dossier.get("output_language", "English"),
                 "candidates": len(dossier["inspection_candidates"]),
                 "cases": scene["cases"]},
    })

    for attempt in range(args.attempts):
        try:
            report = agents.write_briefs(dossier, prioritisation)
        except Exception as exc:  # noqa: BLE001
            with lock:
                stats["writer_error"] += 1
                stats["last_error"] = f"{type(exc).__name__}: {exc}"
            continue
        issues = validate.validate_report(dossier, report)
        sev = _severity(issues, validate)
        with lock:
            stats[f"writer_{sev}"] += 1
            stats["writer_attempts"] += 1
        if sev == "clean" or (sev == "warning" and not args.strict):
            rows.append({
                "agent": "writer",
                "seed": scene["seed"],
                "messages": [
                    {"role": "system",
                     "content": _writer_system(agents, dossier)},
                    {"role": "user",
                     "content": _writer_user(agents, dossier, prioritisation)},
                    {"role": "assistant",
                     "content": json.dumps(report, ensure_ascii=False, indent=2)},
                ],
                "meta": {"issues": len(issues),
                         "language": dossier.get("output_language", "English"),
                         "candidates": len(dossier["inspection_candidates"]),
                         "briefs": len(report.get("inspection_briefs", [])),
                         "cases": scene["cases"]},
            })
            return rows

    with lock:
        stats["scene_dropped_writer"] += 1
    return rows


# The prompt construction below mirrors agents.prioritise / agents.write_briefs
# exactly. It is duplicated rather than refactored so that this file can never
# silently change what the deployed agents send.

def _analyst_user(agents, dossier: dict) -> str:
    candidates = dossier.get("inspection_candidates", [])
    return (f"Factual dossier:\n\n"
            f"{json.dumps(agents._agent_payload(dossier), ensure_ascii=False, indent=2)}"
            f"\n\nThis dossier holds {len(candidates)} inspection candidates: "
            f"{', '.join(r['id'] for r in candidates)}. Rank every one of them. "
            f"Ranking is not selection: a low rank says a record comes later, "
            f"and leaving one out says nothing at all about it.")


def _writer_system(agents, dossier: dict) -> str:
    language = dossier.get("output_language", "English")
    system = agents.WRITER_SYSTEM.replace("{language}", language)
    if language.lower() != "english":
        system += (f"\n\nWrite all free-text values in {language}. Keep the JSON "
                   f"field names and the priority values (high/medium) in English, "
                   f"and keep regulation citations in their official form.")
    return system


def _writer_user(agents, dossier: dict, prioritisation: dict) -> str:
    return ("Factual dossier:\n\n"
            + json.dumps(agents._agent_payload(dossier), ensure_ascii=False, indent=2)
            + "\n\nAnalyst prioritisation:\n\n"
            + json.dumps(prioritisation, ensure_ascii=False, indent=2))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenes", default="data/scenes.jsonl")
    ap.add_argument("--out", default="data/sft_raw.jsonl")
    ap.add_argument("--model",
                    default="nvidia/nemotron-3-super-120b-a12b",
                    help="teacher model id as the endpoint names it")
    ap.add_argument("--base-url", default=None,
                    help="OpenAI-compatible endpoint; defaults to NVIDIA_BASE_URL "
                         "or build.nvidia.com")
    ap.add_argument("--attempts", type=int, default=3,
                    help="rejection-sampling budget per agent per scene")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--strict", action="store_true",
                    help="keep only samples with ZERO issues, not merely "
                         "zero blockers (recommended for the final corpus)")
    args = ap.parse_args()

    agents = _load_agents(args.model, args.base_url)
    import analysis
    import validate

    scenes = []
    with open(args.scenes, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                scenes.append(json.loads(line))
    if args.limit:
        scenes = scenes[:args.limit]

    stats = {k: 0 for k in (
        "analyst_clean", "analyst_warning", "analyst_blocker", "analyst_error",
        "analyst_attempts", "writer_clean", "writer_warning", "writer_blocker",
        "writer_error", "writer_attempts", "scene_dropped_analyst",
        "scene_dropped_writer")}
    stats["last_error"] = ""
    lock = threading.Lock()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    started = time.time()
    written = 0

    with out.open("w", encoding="utf-8") as fh, \
            ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(process_scene, s, agents, analysis, validate,
                               args, stats, lock) for s in scenes]
        for i, fut in enumerate(futures, 1):
            for row in fut.result():
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                written += 1
            if i % 10 == 0 or i == len(futures):
                elapsed = time.time() - started
                print(f"  {i}/{len(futures)} scenes | {written} samples | "
                      f"{elapsed/60:.1f} min", flush=True)

    print(f"\n{written} samples written to {out}\n")
    print("Teacher behaviour (this is a result, keep it for the write-up):")
    for key in sorted(stats):
        if key != "last_error":
            print(f"  {key:<26} {stats[key]}")
    if stats["last_error"]:
        print(f"  last_error                 {stats['last_error']}")

    for agent in ("analyst", "writer"):
        attempts = stats[f"{agent}_attempts"]
        clean = stats[f"{agent}_clean"]
        if attempts:
            print(f"\n  {agent}: {clean}/{attempts} attempts were clean on the "
                  f"first pass of the validator ({100*clean/attempts:.1f}%). "
                  f"{stats[f'scene_dropped_{agent}']} scenes exhausted the "
                  f"{args.attempts}-attempt budget and were dropped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
