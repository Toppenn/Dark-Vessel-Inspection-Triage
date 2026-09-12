# Curiosity v2 — hard-won facts (11–12 Sept 2026)

Read before submitting anything.

| | |
|---|---|
| User / login node | `omc-yzdgu` @ `slogin01` |
| Account | `omc-hackathon` |
| Partition | `hackathon` |
| QOS | `omc-team14` |

## THE constraint: 1 GPU for the whole team

`sacctmgr show qos` gives `omc-team14  GrpTRES=cpu=32,gres/gpu=1`.
GrpTRES is a **group** cap, not per-user: everyone in team14 shares one B300 and
32 CPUs. `gsh-*` and `nrc-*` teams got 4 GPUs; `omc-*` and `ncs-*` got 1.
Asking for more returns `QOSGrpGRES ... Job violates accounting/QOS policy`.
MaxWall is 30 days, so time is not the constraint — GPUs are.

Consequence: teacher generation and evaluation run on build.nvidia.com as
CPU-only jobs; the LoRA uses NVIDIA's single-GPU recipe.

## Hardware

B300 SXM6, **275 GB HBM per GPU**, 256 CPU / 1814 GB RAM per node.
Nemotron-3-Nano BF16 is ~60 GB, so one GPU has large headroom for LoRA.

## Node status

| Nodes | State | Note |
|---|---|---|
| dgx06, 07, 09 | mix | the only schedulable GPU nodes |
| dgx05, dgx08 | drain | GPU XID 31 / 43 faults |
| dgx11–dgx20 | drain | "Drained by CMDaemon" |
| dgx01–04, dgx10 | idle, `Gres=(null)` | **40 B300s Slurm cannot schedule** |

CPU-only jobs *can* land on that last row, which is why the API jobs ask for no
GPU.

## Storage

| Path | Size | Note |
|---|---|---|
| `$HOME` | 50 GB | **purged at hackathon end** |
| `/storage/hackathon_teams/omc-team14` | 300 GB | team, NFS, all nodes |
| `/local`, `/tmp` on compute | 3.2 TB | node-local, not persistent |
| `/raid` | — | **not writable**, despite the NVIDIA deck |

`HF_HOME` must be on `/storage`. Nano BF16 is ~60 GB, Super ~240 GB; in `$HOME`
the first download dies at the quota.

## Enroot / pyxis fix

`srun --container-image=...` fails with
`pyxis: mkdir: cannot create directory '/run/user/1643': Permission denied`
because Slurm steps get no usable `XDG_RUNTIME_DIR`. `cluster_env.sh` sets
`XDG_RUNTIME_DIR`, `ENROOT_RUNTIME_PATH` (/tmp) and `ENROOT_CACHE_PATH` /
`ENROOT_DATA_PATH` (/local). Registry pulls take ~30 min and cache per-node, so
import once to a `.sqsh` on /storage (`sbatch_import_image.sh`).

## Python

Login node is PEP 668 externally-managed; `pip install --user` is refused.
Shared venv at `/storage/hackathon_teams/omc-team14/venv`, exported as
`$DVIT_PY`. Use it in every job script.

## build.nvidia.com model ids (differ from the HF names)

    nvidia/nemotron-3-super-120b-a12b       teacher
    nvidia/nemotron-3-ultra-550b-a55b
    nvidia/nemotron-nano-3-30b-a3b          <- note the word order
    nvidia/nemotron-3-nano-omni-30b-a3b-reasoning
    nvidia/nemotron-3.5-lightning-30b-a3b

## Gotchas that cost time

1. `source "$(dirname "$0")/cluster_env.sh"` breaks under sbatch — Slurm spools
   the script elsewhere. Use `$SLURM_SUBMIT_DIR`.
2. `-A omc-hackathon -p hackathon` required on every job.
3. An interactive `srun` that spends its time limit pulling an image dies before
   running your command. Pull separately.

## Open questions for the mentors

1. Can dgx01–04 and dgx10 have their GPU GRES re-registered? 40 B300s idle.
2. Intended `ENROOT_*` paths, and is there a pre-cached image for B300?
3. Is the 1-GPU cap for `omc-*` teams intentional? `gsh-*` teams have 4.
4. Does the site vLLM support LoRA on hybrid Mamba-2/MoE Nemotron-3, or must
   the adapter be merged before serving?
