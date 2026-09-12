# Progress log

## 12 Sept 2026, 05:00 CEST

### Done
- `finetune/` pipeline written and pushed (branch `feature/ToppenAdvances`).
- **Multi-scene red team: 2,374/2,374 cases across 177 generated scenes,
  guardrail catch rate 1,843/1,843.** Up from 15 cases on 1 demo scene.
  Reproduce: `scene_factory.py --n 200` then `harness_over_scenes.py`.
- Cluster fully characterised — see `CLUSTER_NOTES.md`.
- Container runtime unblocked (enroot XDG fix); image imports successfully.
- Plan re-scoped from 8 GPUs to 1 after finding the QOS cap.

### Running
- Job 6155 — import automodel container to `.sqsh` on /storage.
- Job 6156 — teacher corpus, 120 scenes, Super-120B via build.nvidia.com,
  validator-gated rejection sampling, 8 workers, 8 h limit.

### Not started
- LoRA SFT (`sbatch_sft_1gpu.sh`, needs the corpus + the .sqsh).
- Base-vs-adapter eval (`eval_live.py`).
- README update with the 2,374/2,374 number.
- The "where this sits" section still missing from README (flagged in
  PROJECT.md as the top documentation task).

### Numbers to capture when 6156 finishes
- Teacher first-pass clean rate (how often Super-120B passed the validator with
  no retry) — a result in its own right.
- Scenes that exhausted the 3-attempt budget.
- Case coverage of the curated training set.
