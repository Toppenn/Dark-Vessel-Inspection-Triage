# Fine-tuning: closing the nano gap

This directory answers the mentor's four technical points in one pipeline:

| Mentor point | Where it lands |
|---|---|
| use the cluster for fine-tuning | `sbatch_sft.sh`, `nano_writer_lora.yaml` |
| synthetic data for the fine-tuning phase (Data Designer) | `scene_factory.py`, `surface_vocab.py` |
| a data curation pipeline (Curator) | `curate.py`, `CURATOR.md` |
| fine-tune with Automodel SFT | `nano_writer_lora.yaml` + `sbatch_sft.sh` |

The fifth point — explaining why the project needs an LLM at all — is
`../docs/WHY_AN_LLM.md`.

## The claim being tested

Roadmap objective 4 currently reads: *we use the large model because the small
one fails*. `nemotron-3-nano-30b-a3b` collapses into a repetition loop on the
full dossier and never emits an object. The target is to replace that sentence
with **we fixed the small one**, and to have a number behind it.

That matters beyond the hackathon. The whole public-sector argument is that the
system runs inside the authority's own environment. A 550B or 120B model is a
much harder thing for a regional inspection service to host than a 30B model
with 3.5B active parameters. Making the small model work is not a benchmark
exercise; it is the difference between a deployable product and a demo.

## The pipeline

```
scene_factory.py       facts, sampled deterministically      (CPU, seconds)
   |                   -> src/analysis.py computes the dossier
   v
gen_teacher.py         Super-120B writes briefs;             (1 node, ~2-3 h)
   |                   validate.py accepts or rejects each one
   v
curate.py              dedup, length, leak-free split        (CPU, seconds)
   |
   v
nano_writer_lora.yaml  LoRA SFT of Nano-30B-A3B              (1 node, ~1-2 h)
   |
   v
eval_live.py           held-out scenes, base vs adapter      (1 node, ~1 h)
```

The load-bearing idea is in the second box. **The validator is the data
curator.** A teacher output only enters the corpus if the same executable rules
that gate a real report find no blocking issue in it. The failure modes we are
trying to remove from the small model — citing the AIS carriage requirement
against a broadcasting vessel, moving a coordinate, dropping a high-priority
record — cannot be present in its supervision, because those are precisely
what `validate.py` blocks.

And the teacher's rejection rate is itself a result worth reporting: *the 120B
model needed N attempts per clean scene* is a measurement of the problem the
guardrail exists to solve, taken on real outputs rather than on mutations.

## What runs today with no GPU and no key

Before touching the cluster, this is worth running, because it is the cheapest
strengthening of the existing evidence:

```bash
python finetune/scene_factory.py --n 200 --out data/scenes.jsonl
python finetune/harness_over_scenes.py --scenes data/scenes.jsonl
```

`src/eval_agent.py` builds its 15 adversarial cases from **one** demo scene. A
guardrail rule that holds only because of an accident of that scene's geometry
would pass. Run over 200 generated scenes instead, the harness produces on the
order of 1,800 cases across 130+ distinct worlds — different geographies, zone
sets, closure states, working languages and length distributions. If the catch
rate stays at 100% there, the claim "the guarantees live in code" has evidence
behind it that a single scene cannot give.

If it does *not* stay at 100%, that is more valuable still: it means a rule was
fitted to the demo data, and you found it before a mentor did.

## Running it on Curiosity v2

The cluster is one CPU login node and ten DGX B300 compute nodes, Slurm 25.05,
with enroot/pyxis, Apptainer and rootless Docker available. Three policy points
from the NVIDIA deck that shape everything here:

* **Nothing but Slurm commands on the login node.** Building environments and
  pulling containers included. Every step below runs under `srun`/`sbatch`.
* **`$HOME` is 50 GB; the team shared folder is 300 GB.** One BF16
  Nemotron-3-Nano checkpoint is roughly 60 GB and Super is roughly 240 GB, so
  `HF_HOME` **must** point at the shared folder. Left in `$HOME`, the first
  download fills the quota and dies halfway. This is the single most likely
  way to lose an afternoon.
* **`/tmp` on a compute node is not persistent** and is cleaned when the job
  ends; heavy I/O and compilation go there deliberately, and `TMPDIR` is set to
  `/raid/$SLURM_JOB_ID/tmp`.
* **Home directories are purged when the hackathon ends.** Nothing that matters
  should exist only on the cluster.

### First, fill in four values

```bash
# on the login node
sinfo -o "%P %l %D %G"                    # partition name, time limit, GPUs
sacctmgr show assoc user=$USER format=account,partition
ls -ld /shared/* /project/* /team/* 2>/dev/null   # find the team 300 GB folder
```

Put the answers in `cluster_env.sh` (`DVIT_PARTITION`, `DVIT_ACCOUNT`,
`DVIT_SHARED`). Everything else derives from those.

### Then

```bash
source finetune/cluster_env.sh
git clone https://github.com/Toppenn/Dark-Vessel-Inspection-Triage $DVIT_REPO
git clone https://github.com/NVIDIA-NeMo/Automodel $DVIT_AUTOMODEL_REPO

sbatch finetune/sbatch_gen_teacher.sh          # scenes + teacher + curation
sbatch finetune/sbatch_sft.sh                  # LoRA
RUN_DIR=$DVIT_WORK/runs/sft_<jobid> sbatch finetune/sbatch_eval.sh
```

### Two things to ask the mentors on Wednesday

Both are cheap for them to answer and expensive to get wrong:

1. **Which container images are cached locally for the B300 nodes?** These are
   Blackwell Ultra; the compatible vLLM and NeMo tags move fast, and pulling a
   multi-GB image per job wastes the allocation. `cluster_env.sh` defaults to
   `nvcr.io/nvidia/nemo-automodel:26.04.00` and `vllm/vllm-openai:latest`.
2. **Does the site's vLLM build support LoRA adapters on the hybrid
   Mamba-2/MoE Nemotron-3 architecture?** If not, the adapter has to be merged
   before serving. `sbatch_eval.sh` handles both but the answer decides which.

## Why LoRA and not full SFT

Nemotron-3-Nano-30B-A3B is a hybrid Mamba-2/Transformer MoE: 52 layers, 128
experts plus one shared expert, 6 activated per token, 3.5B active parameters.
NVIDIA's own recipe for this exact model uses LoRA with
`exclude_modules: ["*.out_proj"]`, because the Mamba-2 layers consume
`out_proj.weight` inside a custom kernel where LoRA cannot apply. That
exclusion is copied verbatim into `nano_writer_lora.yaml` and must stay.

Beyond the mechanics: the thing being taught here is narrow and stylistic —
*emit this JSON object, in this register, terminate*. That is what LoRA is for.
Full SFT on a 30B MoE would spend far more of the allocation to change far more
of the model than the task calls for, and would make regression on general
capability a real risk rather than a theoretical one.

## `mask_generation_prompt: true`

This is the one flag in the recipe that is not a preference.

Nemotron-3 is a hybrid-reasoning model. Its chat template inserts an empty
reasoning block into every assistant turn that carries no `reasoning_content`.
Train with loss on that block and the model learns to open its reasoning and
immediately close it — and the failure this whole exercise exists to fix is a
degenerate reasoning loop. Leave it false and you are spending gradient on
exactly the wrong thing.

`preflight_dataset.py` exists to catch that class of mistake before a job runs:
it loads the corpus through the same `ChatDataset` the recipe uses and prints
the decoded supervised span, so you can read it and confirm it is the JSON
object and nothing else.

## Reporting it honestly

Two failure modes of this kind of result, both worth pre-empting in the
write-up:

**It is distillation, and it should be labelled as such.** The small model is
being taught to imitate a large model's validated output on synthetic scenes.
That is a real and useful result. It is not evidence that the small model
*reasons* better, and it says nothing about performance on real Global Fishing
Watch data, whose distribution the scene factory approximates but does not
reproduce.

**The corpus is filtered by the validator, and the evaluation uses the same
validator.** That is close to training on the test metric. The mitigation is
the split — `curate.py` splits by scene, so an adapter is never evaluated on a
scene it was trained on — but the honest framing is narrow: *the fine-tune
raises the rate at which the small model produces output the guardrail accepts,
on scenes it has not seen*. It does not show that the guardrail is right. The
guardrail's own correctness is what `harness_over_scenes.py` measures, and
those are two separate claims that should never be merged into one number.

## Files

| File | What it is |
|---|---|
| `cluster_env.sh` | every cluster-specific value, in one place |
| `scene_factory.py` | synthetic scenes; facts sampled, never generated |
| `surface_vocab.py` | Data Designer config for names and languages; static fallback |
| `gen_teacher.py` | teacher generation with validator-gated rejection sampling |
| `curate.py` | dedup, length filter, coverage report, leak-free split |
| `preflight_dataset.py` | load the corpus as the trainer will, before the job |
| `nano_writer_lora.yaml` | AutoModel LoRA recipe for Nano-30B-A3B |
| `sbatch_gen_teacher.sh` | stage 1 job: serve teacher, generate, curate |
| `sbatch_sft.sh` | stage 2 job: LoRA SFT |
| `sbatch_eval.sh` | stage 3 job: base vs adapter on held-out scenes |
| `eval_live.py` | live-model measurement (the model, not the guardrail) |
| `harness_over_scenes.py` | the existing red team, over hundreds of scenes |
| `CURATOR.md` | mapping from `curate.py` stages to NeMo Curator |
