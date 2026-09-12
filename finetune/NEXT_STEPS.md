# Next steps — Fri 11 Sept to the Wednesday scrum (16 Sept)

Ordered so that something presentable exists even if the cluster fights back.

## Friday / Saturday — no GPU needed, do this first

1. **Run the red team over many worlds.** ~20 minutes of work, and it is the
   result that needs nothing from anyone.

   ```bash
   python finetune/scene_factory.py --n 200 --out data/scenes.jsonl
   python finetune/harness_over_scenes.py --scenes data/scenes.jsonl
   ```

   On 150 generated scenes this produced **1,802 cases across 134 distinct
   worlds, 100% on expected severity** — against the README's current 15/15 on
   one scene. Different geographies, zone sets, closure states, languages and
   length distributions. If any case drops below 100%, that is a rule fitted to
   the demo data and finding it is worth more than the clean number.

   Update the README table with whatever you actually get.

2. **Put the "where this sits" section into the README.** `PROJECT.md` flags it
   as the most important outstanding documentation task and it is still
   pending. A mentor who thinks you are claiming to have built a detector will
   give you the wrong advice all week.

3. **Read `docs/WHY_AN_LLM.md` and decide whether you agree with it.** It is
   written against the project on purpose. The part to sit with: your own
   `eval_agent.clean_report()` is a template baseline, and it passes the
   validator perfectly — so validator pass rate cannot be the argument for the
   model. Have your answer ready before someone else notices.

## Saturday / Sunday — find the cluster's shape

4. On the login node, answer four questions and fill them into
   `finetune/cluster_env.sh`:

   ```bash
   sinfo -o "%P %l %D %G"                             # partition, time limit, GPUs
   sacctmgr show assoc user=$USER format=account,partition
   ls -ld /shared/* /project/* /team/* 2>/dev/null    # the team's 300 GB folder
   squeue -o "%.10i %.12P %.20j %.8u %.2t %.10M %.6D"  # who else is queued
   ```

   **Do not skip the shared-folder one.** `$HOME` is 50 GB; a BF16 Nemotron-3
   Nano checkpoint is ~60 GB and Super is ~240 GB. If `HF_HOME` stays in
   `$HOME` the first download fills the quota and dies halfway through, and you
   will lose an afternoon working out why.

5. Smoke-test the container and the GPUs before trusting a long job:

   ```bash
   source finetune/cluster_env.sh
   srun -N1 --gpus-per-node=8 -t 00:20:00 --pty \
     --container-image="$DVIT_AUTOMODEL_IMAGE" \
     bash -c 'nvidia-smi; python -c "import torch;print(torch.__version__, torch.cuda.device_count())"'
   ```

   If the image does not run on B300, stop and ask — do not start substituting
   tags at random.

## Monday — the corpus

6. `sbatch finetune/sbatch_gen_teacher.sh` (~2–3 h on one node).

   Watch two numbers in the log, both of which belong in the write-up:

   * the teacher's **first-pass clean rate** — how often Super-120B produced a
     report the validator accepted with no retry;
   * how many scenes **exhausted the attempt budget** and were dropped.

   That is a measurement of the problem the guardrail exists for, taken on real
   model output rather than on mutations. It is more interesting than the
   corpus itself.

7. Check the corpus before training on it:

   ```bash
   python finetune/curate.py --in $DVIT_DATA/sft_raw.jsonl \
       --outdir $DVIT_DATA/sft --agent writer
   ```

   Look at the case-coverage table. If `near_threshold_dark` or
   `exactly_threshold_dark` came out thin, the teacher struggled there —
   generate more scenes rather than training on a corpus that skips the hard
   case.

## Tuesday — train and measure

8. `sbatch finetune/sbatch_sft.sh` (~1–2 h). The preflight step runs first; if
   the supervised span it prints is not the JSON object, kill the job.

9. `RUN_DIR=... sbatch finetune/sbatch_eval.sh` (~1 h). Base nano vs LoRA nano,
   on held-out scenes only.

   The result you want on a slide is one table:

   ```
   model                  scenes  collapsed  unparseable  blocked  clean
   nano (base)                40          ?            ?        ?      ?
   nano (LoRA, this work)     40          ?            ?        ?      ?
   ```

   If the collapse column goes to zero, objective 4 is closed and the sentence
   changes from *we use the large one because the small one fails* to *we fixed
   the small one* — with the run behind it.

## Wednesday — what to bring to the scrum

* The multi-world harness number (does not depend on the cluster).
* The teacher's rejection rate (a finding, not a by-product).
* The base-vs-LoRA table, or an honest account of where it got stuck.
* `docs/WHY_AN_LLM.md`, and the proposed A/B with actual inspection staff —
  which is the experiment that settles it and is blocked on talking to a user,
  not on compute.

Two questions worth putting to the mentors, both cheap for them:

1. Which container images are cached locally for the B300 nodes?
2. Does the site's vLLM build support LoRA adapters on the hybrid Mamba-2/MoE
   Nemotron-3 architecture, or does the adapter need merging before serving?

## Explicitly deferred

* **Real GFW data** (roadmap item 2). Do not mix it into the fine-tune week.
  `likely_gear` is absent for unmatched detections and part of the context
  logic will have no input — that is its own problem and it will swallow a day.
* **Multimodal SAR chips** (item 5). Nemotron-3-Nano-Omni exists, but a second
  modality on top of an unfinished fine-tune is how both end up half-done.
* **Calibrating `length_sigma_m`** (item 6). Worth doing, needs literature not
  GPUs, and can happen in parallel by whoever is not driving the cluster.
