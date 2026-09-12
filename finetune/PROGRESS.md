# Progress log

## 12 Sept 2026, ~05:30 CEST

### Done
- `finetune/` pipeline written and pushed.
- **Multi-scene red team: 2,374/2,374 cases across 177 generated scenes**,
  guardrail catch rate 1,843/1,843 — up from 15 cases on 1 demo scene.
- Cluster characterised (`CLUSTER_NOTES.md`); enroot unblocked; shared venv.
- Plan re-scoped 8 GPUs -> 1 after finding the QOS cap.
- Held-out eval set at seed 10000, disjoint from training seeds 0–399.

### In flight
- 6155 import container to .sqsh
- 6156 teacher corpus, 120 scenes  -> 6159 dependent run, 400 scenes
- 6160 baseline eval, base nano writer, analyst fixed at Super-120B

### Observed so far
- Teacher throughput ~4 scenes/min at 8 workers.
- Zero rejections in the first 20 scenes under `--strict`: Super-120B passes
  the validator cleanly. Report this honestly — it means the gap the fine-tune
  must close is between "large model rarely trips the guardrail" and "small
  model cannot produce output at all", not a muddy middle.

### Not started
- LoRA SFT; adapter eval; README "Where this sits" section.
