# Fine-tuning: closing the nano gap

*NVIDIA Open Models Codefest 2026. Runbook, design notes and honest limits.*

This directory answers four points of mentor feedback in one pipeline:

| Mentor point | Where it lands |
|---|---|
| use the cluster for fine-tuning | `sbatch_sft_1gpu.sh`, `nano_writer_lora_1gpu.yaml` |
| synthetic data for the fine-tuning phase (Data Designer) | `scene_factory.py`, `surface_vocab.py` |
| a data curation pipeline (Curator) | `curate.py`, `CURATOR.md` |
| fine-tune with AutoModel SFT | the recipes above + `sbatch_sft_1gpu.sh` |

The fifth point — explaining why the project needs an LLM at all — is
[`../docs/WHY_AN_LLM.md`](../docs/WHY_AN_LLM.md).

---

## The claim being tested

The README's model table says: *the 30B model failed to complete the writer task; it
collapsed into a repetition loop and emitted 49 KB of one repeated sentence.* The goal is to
replace that with **we fixed the small one**, and to have a number behind it.

That matters beyond the hackathon. The whole public-sector argument is that the system runs
inside the authority's own environment. A 120B model is a much harder thing for a regional
inspection service to host than a 30B model with 3.5B active parameters. Making the small
model work is not a benchmark exercise; it is the difference between a deployable product
and a demo.

---

## The pipeline

```
scene_factory.py       facts, sampled deterministically      (CPU, seconds)
   |                   -> src/analysis.py computes the dossier
   v
gen_teacher.py         Super-120B writes briefs;             (CPU, API-bound)
   |                   validate.py accepts or rejects each one
   v
curate.py              dedup, length filter, leak-free split (CPU, seconds)
   |
   v
nano_writer_lora_1gpu.yaml   LoRA SFT of Nano-30B-A3B        (1 GPU)
   |
   v
eval_live.py           held-out scenes, base vs adapter      (CPU via API, or 1 GPU)
```

The load-bearing idea is in the second box. **The validator is the data curator.** A teacher
output enters the corpus only if the same executable rules that gate a real report find no
issue in it. The failure modes we are trying to remove from the small model — citing the AIS
carriage requirement against a broadcasting vessel, moving a coordinate, dropping a
high-priority record — cannot be present in its supervision, because those are precisely
what `validate.py` blocks.

The teacher's rejection rate is itself a result: a measurement of the problem the guardrail
exists to solve, taken on real outputs rather than on mutations.

---

## What runs today with no GPU, no key and no network

This is the strongest thing in the directory and it costs about a minute:

```bash
python finetune/scene_factory.py --n 200 --out data/scenes.jsonl
python finetune/harness_over_scenes.py --scenes data/scenes.jsonl
```

`src/eval_agent.py` builds its 15 adversarial cases from **one** demo scene. A guardrail rule
that holds only because of an accident of that scene's geometry would pass. Run over 200
generated scenes instead — different geographies, zone sets, closure states, working
languages and length distributions — the harness produces on the order of 2,400 cases across
177 distinct worlds.

Latest run: **2,374 / 2,374 on expected severity, guardrail catch rate 1,843 / 1,843,
negative controls 531 / 531.** The README carries the per-family breakdown.

If it ever drops below 100%, that is more valuable still: it means a rule was fitted to the
demo data, and you found it before a mentor did.

---

## Running it on Curiosity v2

Read [`CLUSTER_NOTES.md`](CLUSTER_NOTES.md) first. It records everything that was learned on
the cluster, with the commands that produced each fact. The three that shape this directory:

1. **The team has one GPU.** QOS `omc-team14` is `GrpTRES=cpu=32,gres/gpu=1` — a group cap,
   not per user. Every stage that can avoid the GPU does.
2. **`/raid` is not writable** and `$HOME` is 50 GB and purged at the end. `HF_HOME` lives on
   `/storage`; scratch goes to `/tmp` on the compute node.
3. **Enroot needs `XDG_RUNTIME_DIR`**, which Slurm steps do not get. Without the four
   variables `cluster_env.sh` sets, no container job runs at all.

### Setup, once

```bash
source finetune/cluster_env.sh                  # check the values it prints
git clone https://github.com/NVIDIA-NeMo/Automodel "$DVIT_AUTOMODEL_REPO"

python3 -m venv "$DVIT_VENV"                    # login node is PEP 668 managed
"$DVIT_VENV/bin/pip" install -r finetune/requirements-finetune.txt

sbatch finetune/sbatch_import_image.sh          # container -> .sqsh, ~40 min, once
```

### The three stages

```bash
export NVIDIA_API_KEY='nvapi-...'

# 1. corpus — CPU only, no GPU spent
sbatch --export=ALL,NVIDIA_API_KEY finetune/sbatch_gen_teacher_api.sh

# 2. baseline — CPU only, gives you the "before" row while stage 1 runs
"$DVIT_PY" finetune/scene_factory.py --n 40 --seed 10000 \
    --out "$DVIT_DATA/scenes_holdout.jsonl"
sbatch --export=ALL,NVIDIA_API_KEY finetune/sbatch_eval_api.sh

# 3. train — the one stage that needs the GPU
sbatch finetune/sbatch_sft_1gpu.sh

# 4. after — serve the adapter and score it on the same held-out scenes
RUN_DIR=$DVIT_WORK/runs/sft_<jobid> sbatch finetune/sbatch_eval_vllm.sh
"$DVIT_PY" finetune/eval_live.py --compare \
    "$DVIT_DATA/eval_nano_base.json" "$DVIT_DATA/eval_nano_lora.json"
```

Submit from the repository root: the job scripts resolve `cluster_env.sh` through
`$SLURM_SUBMIT_DIR`, because Slurm spools the script elsewhere and `$(dirname "$0")` points
at the spool directory.

### Held-out scenes

Training uses seeds `0..N`. The evaluation set is generated at seed `10000`, so it is
disjoint **by construction** rather than by relying on how `curate.py` split the corpus. Both
arms of the before/after table must run on the same file.

### Two questions worth putting to the mentors

1. **Is the 1-GPU cap for `omc-*` teams intentional?** `gsh-*` and `nrc-*` teams have 4.
2. **Does the site's vLLM build support LoRA adapters on the hybrid Mamba-2/MoE Nemotron-3
   architecture?** If not, the adapter has to be merged before serving. `sbatch_eval_vllm.sh`
   handles both paths but the answer decides which.

---

## Why LoRA and not full SFT

Nemotron-3-Nano-30B-A3B is a hybrid Mamba-2/Transformer MoE: 52 layers, 128 experts plus one
shared, 6 activated per token, 3.5B active parameters. NVIDIA's own recipe for this exact
model uses LoRA with `exclude_modules: ["*.out_proj"]`, because the Mamba-2 layers consume
`out_proj.weight` inside a custom kernel where LoRA cannot apply. That exclusion is copied
verbatim and must stay.

Beyond the mechanics: the thing being taught here is narrow and stylistic — *emit this JSON
object, in this register, terminate*. That is what LoRA is for. Full SFT on a 30B MoE would
change far more of the model than the task calls for, and would make regression on general
capability a real risk rather than a theoretical one.

---

## `mask_generation_prompt: true`

The one flag in the recipe that is not a preference.

Nemotron-3 is a hybrid-reasoning model. Its chat template inserts an empty reasoning block
into every assistant turn that carries no `reasoning_content`. Train with loss on that block
and the model learns to open its reasoning and immediately close it — and the failure this
whole exercise exists to fix is a degenerate reasoning loop. Leave it false and you are
spending gradient on exactly the wrong thing.

`preflight_dataset.py` exists to catch that class of mistake before a job runs: it loads the
corpus through the same `ChatDataset` the recipe uses and prints the decoded supervised span,
so you can read it and confirm it is the JSON object and nothing else. Both training scripts
run it first.

---

## Reporting it honestly

**It is distillation, and it should be labelled as such.** The small model is being taught to
imitate a large model's validated output on synthetic scenes. That is a real and useful
result. It is not evidence that the small model *reasons* better, and it says nothing about
performance on real Global Fishing Watch data, whose distribution the scene factory
approximates but does not reproduce.

**The corpus is filtered by the validator, and the evaluation uses the same validator.** That
is close to training on the test metric. The mitigation is the disjoint held-out seed range,
but the honest framing is narrow: *the fine-tune raises the rate at which the small model
produces output the guardrail accepts, on scenes it has not seen.* It does not show that the
guardrail is right. The guardrail's own correctness is what `harness_over_scenes.py` measures,
and those are two separate claims that must never be merged into one number.

**Serving stacks must match.** The baseline arm run through build.nvidia.com and the adapter
arm run through local vLLM differ in sampling defaults. Before the final table, re-run the
base arm locally so both arms share a stack — `sbatch_eval_vllm.sh` does both in one
allocation for exactly this reason.

---

## Files

| File | What it is |
|---|---|
| `cluster_env.sh` | every cluster-specific value, in one place |
| `CLUSTER_NOTES.md` | what was learned about Curiosity v2, with the commands that found it |
| `requirements-finetune.txt` | the pipeline's dependencies, kept out of `requirements.txt` |
| `scene_factory.py` | synthetic scenes; facts sampled, never model-generated |
| `surface_vocab.py` | Data Designer config for names and languages; static fallback |
| `gen_teacher.py` | teacher generation with validator-gated rejection sampling |
| `curate.py` | dedup, length filter, coverage report, leak-free split |
| `preflight_dataset.py` | load the corpus as the trainer will, before the job |
| `harness_over_scenes.py` | the existing red team, over hundreds of generated worlds |
| `eval_live.py` | live-model measurement: the model, not the guardrail |
| `CURATOR.md` | where NeMo Curator fits, and why not at this corpus size |
| **default path (1 GPU / API)** | |
| `sbatch_import_image.sh` | container → `.sqsh` on shared storage, once |
| `sbatch_gen_teacher_api.sh` | stage 1: corpus via build.nvidia.com, CPU only |
| `sbatch_eval_api.sh` | stage 3a: baseline via build.nvidia.com, CPU only |
| `nano_writer_lora_1gpu.yaml` + `sbatch_sft_1gpu.sh` | stage 2: LoRA on one GPU |
| `sbatch_eval_vllm.sh` | stage 3b: base vs adapter, both served locally |
| **kept for a cluster with a whole node** | |
| `sbatch_gen_teacher_vllm.sh` | stage 1 self-hosting Super-120B on 8 GPUs |
| `nano_writer_lora_8gpu.yaml` + `sbatch_sft_8gpu.sh` | stage 2 with `ep_size: 4` |
