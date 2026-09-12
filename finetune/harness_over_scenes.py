"""Run the existing red-team harness over many generated scenes, not one.

`src/eval_agent.py` builds its 15 adversarial cases from the single demo
scene. Every mutation is therefore exercised against one geometry, one zone
set, one closure state and one language. A guardrail rule that only works
because of an accident of the demo data would pass.

This runs the same `build_cases` over every scene from `scene_factory.py` and
reports the catch rate per failure family across all of them. It needs no API
key, no network and no GPU — it is the cheapest result on the whole list, and
it is the one that speaks directly to "how do you evaluate agentic output when
you have no ground truth": you do not evaluate the output, you evaluate the
checker, over a distribution of worlds rather than one.

    python finetune/scene_factory.py --n 200 --out data/scenes.jsonl
    python finetune/harness_over_scenes.py --scenes data/scenes.jsonl

Exit code 0 iff every case in every scene lands on its expected severity.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import analysis  # noqa: E402
import eval_agent  # noqa: E402
import validate  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenes", default="data/scenes.jsonl")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--show-misses", type=int, default=10)
    args = ap.parse_args()

    scenes = [json.loads(l) for l in open(args.scenes, encoding="utf-8") if l.strip()]
    if args.limit:
        scenes = scenes[:args.limit]

    families = defaultdict(lambda: [0, 0])   # family -> [hit, total]
    per_case = defaultdict(lambda: [0, 0])   # case name -> [hit, total]
    misses = []
    skipped = 0

    for scene in scenes:
        dossier = analysis.analyse(scene["zones_doc"], scene["detections_doc"])
        try:
            cases = eval_agent.build_cases(dossier)
        except (StopIteration, IndexError, KeyError):
            # A scene without the record a given mutation needs cannot host
            # that mutation. Counting it as a miss would be wrong; hiding it
            # would be worse.
            skipped += 1
            continue

        for name, family, target, expect, payload in cases:
            issues = (validate.validate_prioritisation(dossier, payload)
                      if target == "prioritisation"
                      else validate.validate_report(dossier, payload))
            got = eval_agent.top_severity(issues)
            ok = got == expect
            families[family][0] += int(ok)
            families[family][1] += 1
            per_case[name][0] += int(ok)
            per_case[name][1] += 1
            if not ok and len(misses) < args.show_misses:
                misses.append((scene["seed"], name, expect, got, issues))

    total = sum(v[1] for v in families.values())
    hit = sum(v[0] for v in families.values())
    attacks = sum(v[1] for f, v in families.items() if f != "control")
    caught = sum(v[0] for f, v in families.items() if f != "control")

    print(f"\nRed-team harness over {len(scenes) - skipped} generated scenes "
          f"({skipped} scenes could not host every mutation)\n")
    print("  By failure family (caught / total):")
    for family, (h, t) in sorted(families.items()):
        rate = f"{100*h/t:5.1f}%" if t else "    -"
        print(f"    {family:<22} {h:>5}/{t:<5} {rate}")

    print("\n  By case:")
    for name, (h, t) in sorted(per_case.items(), key=lambda kv: kv[1][0]/max(1, kv[1][1])):
        flag = "" if h == t else "   <-- not universal"
        print(f"    {name:<38} {h:>5}/{t:<5}{flag}")

    print(f"\n  Guardrail catch rate on adversarial cases: {caught}/{attacks}"
          f" ({100*caught/attacks:.2f}%)" if attacks else "")
    print(f"  Overall: {hit}/{total} cases on expected severity")

    if misses:
        print("\n  MISSES (a rule that holds on the demo scene and not in general):")
        for seed, name, expect, got, issues in misses:
            print(f"    scene {seed} / {name}: expected {expect}, got {got}")
            print(f"      {validate.format_issues(issues)[:400]}")

    return 1 if hit != total else 0


if __name__ == "__main__":
    sys.exit(main())
