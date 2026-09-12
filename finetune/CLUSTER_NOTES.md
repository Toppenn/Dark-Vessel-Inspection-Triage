# Curiosity v2 — hard-won facts

*NVIDIA Open Models Codefest 2026. Discovered 11–12 September 2026 on the cluster itself;
every claim here has the command that produced it. Read before submitting anything.*

| | |
|---|---|
| Login | `ssh ssh.axisapps.io -l <one-time-key>`, key from https://axis-raplabhackathon.axisportal.io/apps |
| User / login node | `omc-yzdgu` @ `slogin01` |
| Account | `omc-hackathon` |
| Partition | `hackathon` |
| QOS | `omc-team14` |

---

## THE constraint: one GPU for the whole team

```bash
sacctmgr show qos format=name%15,grptres%40,maxtrespu%30,maxwall
```

```
omc-team14      cpu=32,gres/gpu=1                          30-12:00:00
```

`GrpTRES` is a **group** cap, not per-user: every member of team14 shares one B300 and 32
CPUs. Requesting more returns:

```
srun: error: QOSGrpGRES
srun: error: Unable to allocate resources: Job violates accounting/QOS policy
```

For comparison, `gsh-*` and `nrc-*` teams have `gres/gpu=4`; `omc-*` and `ncs-*` have 1.
`MaxWall` is 30 days, so wall time is not the constraint — GPUs are.

**Consequences, and they shape every script in this directory:**

- Teacher generation and the baseline evaluation run against build.nvidia.com as
  **CPU-only** jobs (`sbatch_gen_teacher_api.sh`, `sbatch_eval_api.sh`). They cost no GPU.
- Training uses NVIDIA's **single-GPU** LoRA recipe (`sbatch_sft_1gpu.sh`,
  `nano_writer_lora_1gpu.yaml`).
- The `_vllm` and `_8gpu` variants are kept for a cluster that gives you a node, and are
  not runnable here as written.

---

## Hardware

```bash
srun -A omc-hackathon -p hackathon -N1 --gpus-per-node=1 -c 8 -t 00:10:00 --pty \
  nvidia-smi --query-gpu=name,memory.total --format=csv
```

```
NVIDIA B300 SXM6 AC, 275040 MiB
```

**275 GB HBM per GPU**, 256 CPU / 1814 GB RAM per node. Nemotron-3-Nano BF16 is ~60 GB of
weights, so one GPU has large headroom for LoRA — the cap costs parallelism, not capability.

---

## Node status (12 September 2026)

```bash
sinfo -p hackathon -o "%20n %10t %40E"
```

| Nodes | State | Reason |
|---|---|---|
| dgx06, dgx07, dgx09 | `mix` | the only schedulable GPU nodes |
| dgx05, dgx08 | `drain` | GPU reset required, XID 31 / XID 43 |
| dgx11 – dgx20 | `drain` | "Drained by CMDaemon" |
| dgx01–04, dgx10 | `idle`, `Gres=(null)` | **40 B300s Slurm cannot schedule** |

The last row is a site fault, confirmed by comparing two nodes:

```bash
scontrol show node dgx01 | grep -i gres   # Gres=(null)
scontrol show node dgx06 | grep -i gres   # Gres=gpu:b300:8(S:0-1)
```

Those five are idle and useless to every team. **CPU-only jobs can land on them**, which is
the second reason the API stages ask for no GPU.

---

## Storage

```bash
df -h | grep -vE 'tmpfs|overlay'
```

| Path | Size | Note |
|---|---|---|
| `$HOME` (`/home/omc-yzdgu`) | 50 GB quota | **purged when the hackathon ends** |
| `/storage/hackathon_teams/omc-team14` | 300 GB team quota | NFS, visible from every node |
| `/local`, `/tmp` on a compute node | 3.2 TB free each | node-local, not persistent |
| `/raid` | — | **not writable**, despite the NVIDIA deck saying to use it |
| `/dev/shm` | 1008 GB | |

`HF_HOME` must live on `/storage`. A BF16 Nano checkpoint is ~60 GB and Super is ~240 GB;
left in `$HOME` the first download fills the quota and fails halfway through.

Find the team folder with `ls -ld /storage/hackathon_teams/*` and `groups`.

---

## Enroot / pyxis: the fix without which no container job runs

Out of the box:

```
pyxis: importing docker image: nvcr.io/nvidia/nemo-automodel:26.04.00
pyxis: mkdir: cannot create directory '/run/user/1643': Permission denied
pyxis: couldn't start container
```

Slurm steps get no usable `XDG_RUNTIME_DIR`. `cluster_env.sh` sets four variables:

```bash
export XDG_RUNTIME_DIR="/tmp/xdg-$(id -u)"
export ENROOT_RUNTIME_PATH="/tmp/enroot-$(id -u)/run"
export ENROOT_CACHE_PATH="/local/enroot-$(id -u)/cache"
export ENROOT_DATA_PATH="/local/enroot-$(id -u)/data"
```

### Import the image once

A registry pull takes about 30 minutes (110 layers) and the enroot cache is **per-node**, so
a job landing elsewhere pays again. `sbatch_import_image.sh` converts it once to a `.sqsh`
on shared storage:

```
/storage/hackathon_teams/omc-team14/automodel-26.04.sqsh
```

`cluster_env.sh` points `DVIT_AUTOMODEL_IMAGE` at that file, and container startup then
takes about 30 seconds on any node.

A first attempt failed usefully: an interactive `srun -t 00:30:00` spent its entire time
limit pulling the image and was killed before running its command. Pull separately.

---

## Python

The login node is PEP 668 externally-managed:

```
error: externally-managed-environment
```

`pip install --user` is refused. The shared venv lives on `/storage` so every compute node
sees it and it survives the `$HOME` purge:

```bash
python3 -m venv $DVIT_SHARED/venv
$DVIT_SHARED/venv/bin/pip install -r finetune/requirements-finetune.txt
```

Installed and verified: `openai 3.13.0`. Exported as `$DVIT_PY`; every job script uses it
rather than the system `python3`.

---

## build.nvidia.com model ids differ from the Hugging Face names

`python src/list_models.py nemotron` against the event key returns 17 models, including:

```
nvidia/nemotron-3-super-120b-a12b               teacher
nvidia/nemotron-3-ultra-550b-a55b
nvidia/nemotron-nano-3-30b-a3b                  <- note the word order
nvidia/nemotron-3-nano-omni-30b-a3b-reasoning
nvidia/nemotron-3.5-lightning-30b-a3b
```

Hugging Face spells the same nano model `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16`.
`cluster_env.sh` keeps both under `DVIT_*_API` and `DVIT_*_MODEL` so the two never get
confused.

---

## Gotchas that cost time

1. **`source "$(dirname "$0")/cluster_env.sh"` breaks under sbatch.** Slurm copies the
   script into a spool directory, so `$0` does not point at the repo and the job dies on
   line one. Use `$SLURM_SUBMIT_DIR`, and submit from the repository root.
2. **`-A omc-hackathon -p hackathon` are required on every job.**
3. **An interactive `srun` that spends its time limit pulling an image** dies before running
   your command.
4. **`/raid/$SLURM_JOB_ID/tmp`**, which the NVIDIA deck recommends for `TMPDIR`, is not
   writable here. With `set -euo pipefail` the `mkdir` kills the job.

---

## Open questions for the mentors

1. Can dgx01–04 and dgx10 have their GPU GRES re-registered? Forty B300s are idle and
   unschedulable.
2. What are the intended `ENROOT_*` paths on this cluster, and is there a pre-cached
   B300-compatible image rather than a per-team registry pull?
3. Is the 1-GPU cap for `omc-*` teams intentional? `gsh-*` and `nrc-*` teams have 4.
4. Does the site's vLLM build support LoRA adapters on the hybrid Mamba-2/MoE Nemotron-3
   architecture, or must the adapter be merged before serving?
