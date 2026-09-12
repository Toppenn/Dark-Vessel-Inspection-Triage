"""Curation — dedup, length filter, balance report, leak-free split.

Where NeMo Curator fits, honestly:

Curator is built for web-scale corpora: RAPIDS/Ray, fuzzy dedup over billions of
documents, quality classifiers, PII redaction. At the scale this project needs
(a few thousand agent traces) its value is not throughput — it is that the
curation steps are named, standard and reproducible rather than ad hoc.

This file implements the same steps in the standard library so the pipeline
runs on the login node, in CI, and on a laptop, with no GPU and no Ray cluster.
`--report-only` prints exactly which stage removed what, so the curation is
auditable in the same way the rest of the system is. If and when the corpus
grows past what fits in memory, `CURATOR.md` in this directory records the
mapping from each stage here to its Curator equivalent.

Two things it does that generic curation does not:

  * it splits by SCENE, not by sample, so an analyst trace and the writer trace
    derived from it can never land on opposite sides of the split — otherwise
    validation accuracy is measured on a scene the model has already seen;
  * it reports coverage per *case template*, because a corpus that dropped all
    the near-threshold records would look healthy on every generic metric and
    be useless for the thing this model has to get right.

    python finetune/curate.py --in data/sft_raw.jsonl --outdir data/sft
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

SHINGLE = 5


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _shingles(text: str) -> set:
    words = _norm(text).split()
    if len(words) < SHINGLE:
        return {" ".join(words)}
    return {" ".join(words[i:i + SHINGLE])
            for i in range(len(words) - SHINGLE + 1)}


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _approx_tokens(row: dict) -> int:
    chars = sum(len(m["content"]) for m in row["messages"])
    return chars // 4


def load(path: Path) -> list:
    rows = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def curate(rows: list, args) -> tuple:
    report = {}
    report["input"] = len(rows)

    # 1. Well-formedness. The assistant turn must parse as the JSON object the
    #    prompt asks for; a sample that does not is not a demonstration.
    kept = []
    for row in rows:
        try:
            obj = json.loads(row["messages"][-1]["content"])
            if not isinstance(obj, dict):
                raise ValueError
        except (json.JSONDecodeError, ValueError, KeyError, IndexError):
            continue
        kept.append(row)
    report["after_wellformed"] = len(kept)

    # 2. Agent filter.
    if args.agent != "all":
        kept = [r for r in kept if r.get("agent") == args.agent]
    report["after_agent_filter"] = len(kept)

    # 3. Exact deduplication on (prompt, completion).
    seen = set()
    deduped = []
    for row in kept:
        h = hashlib.sha256(
            ("".join(m["content"] for m in row["messages"])).encode()
        ).hexdigest()
        if h in seen:
            continue
        seen.add(h)
        deduped.append(row)
    report["after_exact_dedup"] = len(deduped)

    # 4. Near-duplicate removal on the user turn. Scenes are sampled
    #    independently, so a high overlap means the sampler produced two nearly
    #    identical scenes and the model would see the same lesson twice.
    if args.fuzzy_threshold < 1.0:
        buckets = defaultdict(list)
        survivors = []
        for row in deduped:
            sh = _shingles(row["messages"][1]["content"])
            key = min(hashlib.md5(s.encode()).hexdigest() for s in sh)[:6] \
                if sh else "0"
            clash = False
            for other in buckets[key]:
                if _jaccard(sh, other) >= args.fuzzy_threshold:
                    clash = True
                    break
            if not clash:
                buckets[key].append(sh)
                survivors.append(row)
        deduped = survivors
    report["after_fuzzy_dedup"] = len(deduped)

    # 5. Length filter. Over the sequence budget the sample is truncated during
    #    training, and a truncated completion teaches the model to stop early —
    #    which is the under-reporting failure we treat as blocking.
    sized = [r for r in deduped if args.min_tokens <= _approx_tokens(r) <= args.max_tokens]
    report["after_length_filter"] = len(sized)
    report["dropped_too_long"] = sum(1 for r in deduped
                                     if _approx_tokens(r) > args.max_tokens)

    # 6. Split by scene seed. No scene appears on both sides.
    seeds = sorted({r["seed"] for r in sized})
    rng = random.Random(args.split_seed)
    rng.shuffle(seeds)
    n_val = max(1, int(len(seeds) * args.val_fraction))
    val_seeds = set(seeds[:n_val])
    train = [r for r in sized if r["seed"] not in val_seeds]
    val = [r for r in sized if r["seed"] in val_seeds]
    report["scenes"] = len(seeds)
    report["train"] = len(train)
    report["val"] = len(val)

    return train, val, report


def coverage(rows: list) -> tuple:
    cases = Counter()
    langs = Counter()
    for row in rows:
        for case in row.get("meta", {}).get("cases", []):
            cases[case] += 1
        langs[row.get("meta", {}).get("language", "?")] += 1
    return cases, langs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default="data/sft_raw.jsonl")
    ap.add_argument("--outdir", default="data/sft")
    ap.add_argument("--agent", default="writer",
                    choices=["writer", "analyst", "all"])
    ap.add_argument("--fuzzy-threshold", type=float, default=0.85)
    ap.add_argument("--min-tokens", type=int, default=200)
    ap.add_argument("--max-tokens", type=int, default=12000)
    ap.add_argument("--val-fraction", type=float, default=0.15)
    ap.add_argument("--split-seed", type=int, default=7)
    ap.add_argument("--report-only", action="store_true")
    args = ap.parse_args()

    rows = load(Path(args.inp))
    train, val, report = curate(rows, args)

    print("Curation stages:")
    for key in ("input", "after_wellformed", "after_agent_filter",
                "after_exact_dedup", "after_fuzzy_dedup",
                "after_length_filter", "dropped_too_long", "scenes",
                "train", "val"):
        print(f"  {key:<24} {report[key]}")

    cases, langs = coverage(train)
    print("\nTraining-set case coverage:")
    for case, n in sorted(cases.items(), key=lambda kv: -kv[1]):
        print(f"  {case:<26} {n}")
    print("\nTraining-set working language:")
    for lang, n in sorted(langs.items(), key=lambda kv: -kv[1]):
        print(f"  {lang:<26} {n}")

    missing = [c for c in cases if cases[c] < 5]
    if missing:
        print("\n  WARNING: fewer than 5 training scenes touch these cases: "
              + ", ".join(sorted(missing)))

    if args.report_only:
        return 0

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    for name, part in (("train", train), ("validation", val)):
        path = outdir / f"{name}.jsonl"
        with path.open("w", encoding="utf-8") as fh:
            for row in part:
                fh.write(json.dumps({"messages": row["messages"]},
                                    ensure_ascii=False) + "\n")
        print(f"\n{len(part):>5} -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
