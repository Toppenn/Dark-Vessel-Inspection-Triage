# Curiosity v2 — what we learned, 11–12 Sept 2026

Everything here was discovered the hard way. Read before submitting anything.

## Identity

| | |
|---|---|
| Login | `ssh ssh.axisapps.io -l <one-time-key>` via https://axis-raplabhackathon.axisportal.io/apps |
| User / node | `omc-yzdgu` @ `slogin01` |
| Account | `omc-hackathon` |
| Partition | `hackathon` |
| QOS | `omc-team14` |

## THE constraint: 1 GPU for the whole team

`sacctmgr show qos` gives `omc-team14  GrpTRES=cpu=32,gres/gpu=1`.

GrpTRES is a **group** cap, not per-user. Everyone in team14 shares one B300 and
32 CPUs. `gsh-*` and `nrc-*` teams got 4 GPUs; `omc-*` and `ncs-*` got 1.

Asking for more returns `QOSGrpGRES ... Job violates accounting/QOS policy`.
MaxWall is 30 days, so wall time is not the constraint — GPUs are.

Consequence: the teacher runs on build.nvidia.com (CPU-only job), and the LoRA
uses NVIDIA's single-GPU recipe. See `sbatch_gen_teacher_api.sh` and
`sbatch_sft_1gpu.sh`.

## Hardware

- B300 SXM6, **275040 MiB (~275 GB) HBM per GPU**. Nemotron-3-Nano BF16 is
  ~60 GB, so a single GPU has large headroom for LoRA.
- 256 CPU / 1814 GB RAM per node.

## Node status (12 Sept 2026)

| Nodes | State | Note |
|---|---|---|
| dgx06, 07, 09 | `mix` | the only schedulable GPU nodes |
| dgx05, dgx08 | `drain` | GPU XID 31 / XID 43 faults |
| dgx11–dgx20 | `drain` | "Drained by CMDaemon" |
| dgx01–04, dgx10 | `idle` but `Gres=(null)` | **40 B300s Slurm cannot schedule** |

The last row is a site fault worth chasing: those nodes are idle and useless to
everyone. CPU-only jobs *can* land on them, which is why the teacher job asks
for no GPU.

## Storage

| Path | Size | Note |
|---|---|---|
| `$HOME` (`/home/omc-yzdgu`) | 50 GB quota | **purged at hackathon end** |
| `/storage/hackathon_teams/omc-team14` | 300 GB team quota | shared, NFS, all nodes |
| `/local`, `/tmp` on compute nodes | 3.2 TB free | node-local, not persistent |
| `/raid` | — | **not writable**, despite the NVIDIA deck |
| `/dev/shm` | 1008 GB | |

`HF_HOME` must live on `/storage`. A BF16 Nano checkpoint is ~60 GB and Super is
~240 GB; left in `$HOME` the first download dies at the 50 GB quota.

## Enroot / pyxis: the fix

Out of the box `srun --container-image=...` fails with:

    pyxis: mkdir: cannot create directory '/run/user/1643': Permission denied

Slurm steps get no usable `XDG_RUNTIME_DIR`. `cluster_env.sh` sets:

    export XDG_RUNTIME_DIR="/tmp/xdg-$(id -u)"
    export ENROOT_RUNTIME_PATH="/tmp/enroot-$(id -u)/run"
    export ENROOT_CACHE_PATH="/local/enroot-$(id -u)/cache"
    export ENROOT_DATA_PATH="/local/enroot-$(id -u)/data"

Pulling `nvcr.io/nvidia/nemo-automodel:26.04.00` from the registry takes ~30 min
and the cache is per-node. Import it once to a `.sqsh` on `/storage`
(`sbatch_import_image.sh`) and point `DVIT_AUTOMODEL_IMAGE` at the file.

## Python

Login node is PEP 668 externally-managed; `pip install --user` is refused.
Shared venv at `/storage/hackathon_teams/omc-team14/venv` (openai 3.13.0),
exported as `$DVIT_PY`. Use it in every job script.

## build.nvidia.com model ids (differ from the HF names!)

    nvidia/nemotron-3-super-120b-a12b          teacher
    nvidia/nemotron-3-ultra-550b-a55b
    nvidia/nemotron-nano-3-30b-a3b             <- NOTE the word order
    nvidia/nemotron-3-nano-omni-30b-a3b-reasoning
    nvidia/nemotron-3.5-lightning-30b-a3b

`src/agents.py` documents the nano as `nemotron-3-nano-30b-a3b`; the live
endpoint is `nemotron-nano-3-30b-a3b`. Fix before the eval stage.

## Gotchas that cost time

1. `source "$(dirname "$0")/cluster_env.sh"` breaks under sbatch — Slurm spools
   the script elsewhere. Use `$SLURM_SUBMIT_DIR`.
2. `-A omc-hackathon -p hackathon` are required on every job.
3. An interactive `srun` that spends its whole time limit pulling an image dies
   before running your command. Pull separately.

## Open questions for the mentors

1. Can dgx01–04 and dgx10 have their GPU GRES re-registered? 40 B300s idle.
2. What are the intended `ENROOT_*` paths, and is there a pre-cached image for
   the B300 nodes?
3. Is the 1-GPU cap for `omc-*` teams intentional? `gsh-*` teams have 4.
4. Does the site's vLLM build support LoRA on the hybrid Mamba-2/MoE
   Nemotron-3 architecture, or must the adapter be merged before serving?
