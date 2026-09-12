"""Preflight: load the curated corpus exactly as the training job will.

AutoModel's `ChatDataset` consumes OpenAI-format `messages` JSONL directly, so
no custom dataset code is needed — but it does apply the model's chat template
and derive the loss mask from it, and that is where a corpus quietly goes
wrong. This script loads the data through the same class the recipe uses and
prints what the trainer will actually see:

  * how many samples survive `seq_length` (a truncated brief is the
    under-reporting failure, taught on purpose)
  * what fraction of each sample carries loss (should be the brief, not the
    4 kB system prompt)
  * the decoded supervised span of one sample, so you can read it and confirm
    it is the JSON object and nothing else

Run this on a compute node before submitting a training job. It takes a minute
and it catches the mistakes that otherwise surface as a loss curve that never
moves.

    srun -N1 --gpus-per-node=1 --pty \
      python finetune/preflight_dataset.py \
        --path $DVIT_DATA/sft/train.jsonl \
        --model nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16 \
        --seq-length 16384
"""

from __future__ import annotations

import argparse
import sys

IGNORE_INDEX = -100


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--seq-length", type=int, default=16384)
    ap.add_argument("--show", type=int, default=1)
    ap.add_argument("--mask-generation-prompt", default="true",
                    choices=["true", "false"])
    args = ap.parse_args()

    from transformers import AutoTokenizer
    from nemo_automodel.components.datasets.llm import ChatDataset

    tok = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True)
    ds = ChatDataset(
        path_or_dataset_id=args.path,
        tokenizer=tok,
        seq_length=args.seq_length,
        padding="do_not_pad",
        truncation="do_not_truncate",
        # Nemotron is a hybrid-reasoning model: its chat template inserts an
        # empty reasoning block into every assistant turn that has no
        # reasoning_content. Training on that block teaches the model only to
        # close it immediately, which is not what we want to spend gradient on.
        mask_generation_prompt=(args.mask_generation_prompt == "true"),
        skip_invalid_samples=True,
    )

    lengths, supervised_frac, over = [], [], 0
    for i in range(len(ds)):
        item = ds[i]
        ids = item["input_ids"]
        labels = item["labels"]
        n = len(ids)
        sup = sum(1 for t in labels if t != IGNORE_INDEX)
        lengths.append(n)
        supervised_frac.append(sup / max(1, n))
        if n > args.seq_length:
            over += 1

    if not lengths:
        print("EMPTY DATASET — nothing to train on.", file=sys.stderr)
        return 1

    lengths_sorted = sorted(lengths)
    frac_sorted = sorted(supervised_frac)

    def pct(xs, p):
        return xs[min(len(xs) - 1, int(len(xs) * p))]

    print(f"samples                 {len(ds)}")
    print(f"over seq_length         {over}  "
          f"({100*over/len(ds):.1f}% — must be 0 before you launch)")
    print(f"tokens  min/med/p95/max {lengths_sorted[0]} / "
          f"{pct(lengths_sorted, 0.5)} / {pct(lengths_sorted, 0.95)} / "
          f"{lengths_sorted[-1]}")
    print(f"supervised fraction     min {frac_sorted[0]:.3f}  "
          f"med {pct(frac_sorted, 0.5):.3f}  max {frac_sorted[-1]:.3f}")
    if pct(frac_sorted, 0.5) < 0.05:
        print("  WARNING: under 5% of the median sample carries loss. The "
              "system prompt is long, so some of this is expected, but check "
              "the decoded span below is the JSON object.")

    for i in range(min(args.show, len(ds))):
        item = ds[i]
        sup_ids = [t for t in item["labels"] if t != IGNORE_INDEX]
        print(f"\n--- sample {i}: supervised span ({len(sup_ids)} tokens), "
              f"first 600 chars ---")
        print(tok.decode(sup_ids)[:600])
        print("--- last 200 chars ---")
        print(tok.decode(sup_ids)[-200:])

    print("\nWhat you are checking for: the supervised span starts with '{' "
          "and ends with '}', and contains no part of the system prompt.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
