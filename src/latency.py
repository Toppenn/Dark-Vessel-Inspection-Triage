"""Latency instrumentation (Roadmap Task 4.2: optimise the full-flow latency).

You optimise what you measure. This times each stage of the pipeline so the
dominant cost is visible rather than guessed at, and so a model swap can be
compared on wall time, not vibes.

Two paths:
  - The deterministic path (load -> cross-reference -> validate) always runs:
    no API key, no network. It is the engine plus the guardrail.
  - The model path (analyst -> writer) runs only when NVIDIA_API_KEY is set,
    because it makes real calls that cost money and take seconds.

The finding this is built to expose: the deterministic engine and validator are
sub-millisecond and scale linearly with the detection count, while each model
call is orders of magnitude slower. So the only latency levers that matter are
model choice (ANALYST_MODEL / WRITER_MODEL — nano vs super vs ultra) and the
MAX_TOKENS ceiling; the two calls are inherently sequential, because the writer
consumes the analyst's output.

    python src/latency.py                 # deterministic path only
    python src/latency.py --model-repeat 3   # + real model calls (needs a key)
"""

import argparse
import os
import statistics
import sys
import time

import analysis
import data
import eval_agent
import validate


def _timed(fn, repeat: int) -> float:
    """Median wall time of fn() over `repeat` runs, in milliseconds."""
    samples = []
    for _ in range(repeat):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1000.0)
    return statistics.median(samples)


def deterministic_breakdown(repeat: int) -> dict:
    """Time the no-model path. Returns {stage: median_ms}."""
    zones_doc = data.load_zones()
    detections_doc = data.load_detections()
    dossier = analysis.analyse(zones_doc, detections_doc)
    clean_prio = eval_agent.clean_prioritisation(dossier)
    clean_rep = eval_agent.clean_report(dossier)

    return {
        "load (zones + detections)": _timed(
            lambda: (data.load_zones(), data.load_detections()), repeat),
        "analyse (cross-reference)": _timed(
            lambda: analysis.analyse(zones_doc, detections_doc), repeat),
        "validate_prioritisation": _timed(
            lambda: validate.validate_prioritisation(dossier, clean_prio), repeat),
        "validate_report": _timed(
            lambda: validate.validate_report(dossier, clean_rep), repeat),
    }, dossier


def model_breakdown(dossier: dict, repeat: int) -> dict:
    """Time the two model calls. Requires NVIDIA_API_KEY. Returns {stage: ms}."""
    import agents  # deferred: the deterministic path must import without the SDK

    prio_holder = {}

    def call_analyst():
        prio_holder["p"] = agents.prioritise(dossier)

    analyst_ms = _timed(call_analyst, repeat)
    prioritisation = prio_holder["p"]
    writer_ms = _timed(lambda: agents.write_briefs(dossier, prioritisation), repeat)
    return {
        f"analyst prioritise ({agents.ANALYST_MODEL})": analyst_ms,
        f"writer write_briefs ({agents.WRITER_MODEL})": writer_ms,
    }


def _print_section(title: str, rows: dict) -> float:
    print(f"\n  {title}")
    subtotal = 0.0
    for stage, ms in rows.items():
        print(f"    {stage:<44} {ms:9.3f} ms")
        subtotal += ms
    print(f"    {'-' * 44} {'-' * 9}")
    print(f"    {'subtotal':<44} {subtotal:9.3f} ms")
    return subtotal


def main() -> int:
    parser = argparse.ArgumentParser(description="Pipeline latency breakdown")
    parser.add_argument("--repeat", type=int, default=200,
                        help="runs to median over for the deterministic path")
    parser.add_argument("--model-repeat", type=int, default=0,
                        help="runs for each model call (0 = skip the model path; "
                             "each run is a real, billed call)")
    args = parser.parse_args()

    det, dossier = deterministic_breakdown(args.repeat)
    n = dossier["total_detections"]
    print(f"\nPipeline latency — {n} detections, "
          f"median of {args.repeat} runs (deterministic path)")
    det_total = _print_section(
        "Deterministic path (no model, no network):", det)

    total = det_total
    if args.model_repeat > 0:
        if not os.environ.get("NVIDIA_API_KEY"):
            print("\n  Model path skipped: NVIDIA_API_KEY is not set.")
        else:
            mdl = model_breakdown(dossier, args.model_repeat)
            total += _print_section(
                f"Model path (median of {args.model_repeat} real call(s)):", mdl)
    else:
        print("\n  Model path skipped (--model-repeat 0). Each model call is a "
              "billed network round-trip and dominates total latency.")

    print(f"\n  {'TOTAL measured':<44} {total:9.3f} ms")
    print(f"\n  Per-detection deterministic cost: "
          f"{det_total / max(n, 1):.4f} ms/detection.")
    print("  Levers: ANALYST_MODEL / WRITER_MODEL (a smaller Nemotron cuts the "
          "dominant cost); MAX_TOKENS ceiling. The two model calls are "
          "sequential — the writer needs the analyst's output.\n")
    return 0


def _selfcheck() -> None:
    """Runnable check: the deterministic breakdown is well-formed and cheap."""
    det, dossier = deterministic_breakdown(20)
    assert set(det) == {"load (zones + detections)", "analyse (cross-reference)",
                        "validate_prioritisation", "validate_report"}
    assert all(ms >= 0 for ms in det.values())
    # The engine is the point: the whole no-model path must be well under 100 ms.
    assert sum(det.values()) < 100.0, f"deterministic path too slow: {det}"
    print("latency self-check: deterministic breakdown well-formed and sub-100ms")


if __name__ == "__main__":
    if "--self-check" in sys.argv:
        _selfcheck()
    else:
        sys.exit(main())
