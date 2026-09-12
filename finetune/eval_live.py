"""Live-model evaluation — the number the fine-tune has to move.

`src/eval_agent.py` measures the GUARDRAIL: given mutations, does the validator
fire. This measures the MODEL: given real scenes, how often does it produce
something the guardrail lets through, unaided.

It is the missing half of the pair, and it is what turns
"we use the large model because the small one fails" into a measurement:

    model                       scenes  collapse  unparseable  blocked  clean
    nano  (base)                    40        14            9        11      6
    nano  (LoRA, this work)         40         0            1         3     36
    super (teacher, reference)      40         0            0         2     38

Run it on held-out scenes — the ones curate.py put in the validation split —
so the corpus the adapter was trained on is not the corpus it is scored on.

    python finetune/eval_live.py \
        --scenes $DVIT_DATA/scenes.jsonl --held-out $DVIT_DATA/sft/validation.jsonl \
        --model nano-lora --base-url http://127.0.0.1:8000/v1 \
        --label "nano (LoRA)" --out $DVIT_DATA/eval_nano_lora.json

Add `--compare a.json b.json ...` to print the table from saved runs.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

OUTCOMES = ["clean", "warning", "blocked", "unparseable", "collapsed", "error"]


def _load_agents(model: str, base_url: str | None):
    if base_url:
        os.environ["NVIDIA_BASE_URL"] = base_url
    os.environ["NEMOTRON_MODEL"] = model
    os.environ["ANALYST_MODEL"] = os.environ.get("ANALYST_MODEL_OVERRIDE", model)
    os.environ["WRITER_MODEL"] = model
    os.environ.setdefault("NVIDIA_API_KEY", "local")
    import agents
    return agents


def _classify(exc: Exception) -> str:
    text = str(exc)
    if "repetition loop" in text or "collapsed" in text:
        return "collapsed"
    if "Could not parse" in text or "JSON" in text or "truncated" in text:
        return "unparseable"
    return "error"


def evaluate_scene(scene, agents, analysis, validate, args, lock, rows):
    dossier = analysis.analyse(scene["zones_doc"], scene["detections_doc"])
    started = time.time()
    row = {"seed": scene["seed"],
           "candidates": len(dossier["inspection_candidates"]),
           "language": dossier.get("output_language", "English")}

    # The analyst is held fixed unless ANALYST_MODEL_OVERRIDE says otherwise, so
    # the number measures the writer and not the pair. Its output is taken as
    # given: we are scoring the brief, not the ranking.
    try:
        prioritisation = agents.prioritise(dossier)
    except Exception as exc:  # noqa: BLE001
        row.update(outcome="analyst_" + _classify(exc), seconds=time.time() - started,
                   issues=[], detail=str(exc)[:300])
        with lock:
            rows.append(row)
        return

    try:
        report = agents.write_briefs(dossier, prioritisation)
    except Exception as exc:  # noqa: BLE001
        row.update(outcome=_classify(exc), seconds=time.time() - started,
                   issues=[], detail=str(exc)[:300])
        with lock:
            rows.append(row)
        return

    issues = validate.validate_report(dossier, report)
    if validate.has_blockers(issues):
        outcome = "blocked"
    elif issues:
        outcome = "warning"
    else:
        outcome = "clean"

    row.update(outcome=outcome, seconds=time.time() - started,
               issues=[{"severity": s, "where": w, "message": m}
                       for s, w, m in issues],
               briefs=len(report.get("inspection_briefs", [])))
    with lock:
        rows.append(row)


def summarise(rows: list, label: str) -> dict:
    counts = Counter(r["outcome"] for r in rows)
    times = [r["seconds"] for r in rows if r.get("seconds")]
    # A blocking issue's message is the thing to report: "the model cited the
    # AIS carriage rule against a broadcasting vessel 4 times" is a finding.
    blockers = Counter()
    for r in rows:
        for issue in r.get("issues", []):
            if issue["severity"].upper().startswith("BLOCK"):
                blockers[issue["message"][:90]] += 1
    return {
        "label": label,
        "scenes": len(rows),
        "counts": dict(counts),
        "median_seconds": round(statistics.median(times), 1) if times else None,
        "p95_seconds": round(sorted(times)[int(len(times) * 0.95)], 1) if times else None,
        "top_blocking_issues": blockers.most_common(8),
        "rows": rows,
    }


def print_table(summaries: list) -> None:
    keys = ["clean", "warning", "blocked", "unparseable", "collapsed", "error",
            "analyst_collapsed", "analyst_unparseable", "analyst_error"]
    present = [k for k in keys
               if any(s["counts"].get(k) for s in summaries)]
    head = f"{'model':<30}{'scenes':>7}" + "".join(f"{k:>14}" for k in present) \
           + f"{'med s':>8}"
    print("\n" + head)
    print("-" * len(head))
    for s in summaries:
        line = f"{s['label']:<30}{s['scenes']:>7}"
        for k in present:
            line += f"{s['counts'].get(k, 0):>14}"
        line += f"{s['median_seconds'] if s['median_seconds'] else '-':>8}"
        print(line)
    print()
    for s in summaries:
        if s["top_blocking_issues"]:
            print(f"{s['label']} — blocking issues by frequency:")
            for msg, n in s["top_blocking_issues"]:
                print(f"  {n:>3}x  {msg}")
            print()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--compare", nargs="*", default=None,
                    help="print the table from saved --out files and exit")
    ap.add_argument("--scenes", default="data/scenes.jsonl")
    ap.add_argument("--held-out", default=None,
                    help="validation.jsonl from curate.py; restricts evaluation "
                         "to scenes the adapter never saw")
    ap.add_argument("--model", default="nvidia/nemotron-3-nano-30b-a3b")
    ap.add_argument("--base-url", default=None)
    ap.add_argument("--label", default=None)
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    if args.compare:
        print_table([json.load(open(p, encoding="utf-8")) for p in args.compare])
        return 0

    scenes = [json.loads(l) for l in open(args.scenes, encoding="utf-8") if l.strip()]

    if args.held_out and Path(args.held_out).exists():
        # curate.py writes only `messages`, so recover the held-out seeds from
        # the raw file next to it if present; otherwise fall back to the tail.
        raw = Path(args.held_out).parent.parent / "sft_raw.jsonl"
        held = set()
        if raw.exists():
            val_texts = {json.loads(l)["messages"][1]["content"][:400]
                         for l in open(args.held_out, encoding="utf-8") if l.strip()}
            for line in open(raw, encoding="utf-8"):
                if not line.strip():
                    continue
                row = json.loads(line)
                if row["messages"][1]["content"][:400] in val_texts:
                    held.add(row["seed"])
        if held:
            scenes = [s for s in scenes if s["seed"] in held]
            print(f"restricted to {len(scenes)} held-out scenes")

    scenes = scenes[:args.n]
    agents = _load_agents(args.model, args.base_url)
    import analysis
    import validate

    rows: list = []
    lock = threading.Lock()
    started = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(evaluate_scene, s, agents, analysis, validate,
                               args, lock, rows) for s in scenes]
        for i, fut in enumerate(futures, 1):
            fut.result()
            if i % 5 == 0 or i == len(futures):
                print(f"  {i}/{len(futures)}  "
                      f"({(time.time()-started)/60:.1f} min)", flush=True)

    summary = summarise(rows, args.label or args.model)
    print_table([summary])

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(summary, fh, ensure_ascii=False, indent=2)
        print(f"written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
