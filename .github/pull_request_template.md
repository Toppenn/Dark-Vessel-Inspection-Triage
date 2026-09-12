## What this changes

<!-- One or two sentences. If it adds a validator rule, say which failure it catches
     and where you saw a model produce it. -->

## Checks

```
python src/main.py --cross-reference-only
python src/test_caution.py
python src/eval_agent.py
python finetune/scene_factory.py --n 200 --out data/scenes.jsonl
python finetune/harness_over_scenes.py --scenes data/scenes.jsonl
```

- [ ] All five pass
- [ ] `test_caution.py` reports 79/79 with the SDK installed (76/79 without)
- [ ] `eval_agent.py` reports 15/15, control 3/3
- [ ] `harness_over_scenes.py` reports 100% on every failure family, and the
      catch-rate line is unchanged or better

## Did any check change?

- [ ] No check was weakened, skipped, or deleted to make this pass

<!-- If a check did change, explain here why the check was wrong rather than the
     code. A failing check is usually the system being right. -->

## If this touches the engine or the validator

- [ ] No model computes a figure, position, distance or classification
- [ ] Missing critical data still raises rather than defaulting
- [ ] New validator rules have both a case that must fire and a well-formed case
      that must not
- [ ] The new rule was checked against the multi-scene harness, not only the demo
      scene — a rule that passes on one geometry may be fitted to it
- [ ] The README sample output still matches the real output (`diff`, don't eyeball)

## If this touches `finetune/`

- [ ] No generated artefact (`data/`, `logs/`, checkpoints) is committed
- [ ] Cluster-specific values live in `cluster_env.sh`, not in a job script
