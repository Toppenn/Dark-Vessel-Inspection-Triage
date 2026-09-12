#!/bin/bash
# Cluster settings for Curiosity v2 (NVIDIA Open Models Codefest 2026).
# Source this from every job script and from your interactive shell:
#
#   source finetune/cluster_env.sh
#
# Everything cluster-specific lives here so nothing else in finetune/ has to
# know what machine it is on. The values below were discovered on the cluster
# and are recorded, with the commands that found them, in CLUSTER_NOTES.md.

# --- Scheduler ----------------------------------------------------------------
export DVIT_ACCOUNT="${DVIT_ACCOUNT:-omc-hackathon}"
export DVIT_PARTITION="${DVIT_PARTITION:-hackathon}"

# THE constraint: QOS omc-team14 has GrpTRES=cpu=32,gres/gpu=1. That is a GROUP
# cap — one B300 and 32 CPUs for the whole team, not per user. Asking for more
# returns QOSGrpGRES. Default to 1 and override deliberately where a multi-GPU
# job is genuinely intended and the cap has been raised.
export DVIT_GPUS_PER_NODE="${DVIT_GPUS_PER_NODE:-1}"

# --- Storage ------------------------------------------------------------------
# $HOME is 50 GB and is purged when the hackathon ends. A BF16 Nemotron-3-Nano
# checkpoint is ~60 GB and Super is ~240 GB, so the Hugging Face cache MUST NOT
# live in $HOME: the first download fills the quota and fails halfway.
export DVIT_SHARED="${DVIT_SHARED:-/storage/hackathon_teams/omc-team14}"
export DVIT_WORK="${DVIT_WORK:-$DVIT_SHARED/dvit}"
export DVIT_DATA="${DVIT_DATA:-$DVIT_WORK/data}"

export HF_HOME="${HF_HOME:-$DVIT_SHARED/hf}"
export HF_HUB_CACHE="$HF_HOME/hub"
export HUGGINGFACE_HUB_CACHE="$HF_HUB_CACHE"
export TRANSFORMERS_CACHE="$HF_HOME"
# The Nemotron Open Model License may require accepting terms on the model page
# before a download succeeds; set a token here if you hit a 401/403.
export HF_TOKEN="${HF_TOKEN:-}"

mkdir -p "$DVIT_WORK" "$DVIT_DATA" "$HF_HOME" 2>/dev/null

# --- Python -------------------------------------------------------------------
# The login node is PEP 668 externally-managed, so `pip install --user` is
# refused. A shared venv on /storage is visible from every compute node and
# survives the $HOME purge.
#
#   python3 -m venv $DVIT_SHARED/venv
#   $DVIT_SHARED/venv/bin/pip install -r finetune/requirements-finetune.txt
export DVIT_VENV="${DVIT_VENV:-$DVIT_SHARED/venv}"
export DVIT_PY="${DVIT_PY:-$DVIT_VENV/bin/python}"

# --- Containers ---------------------------------------------------------------
# Enroot needs XDG_RUNTIME_DIR, which Slurm steps do not get on this cluster.
# Without these four lines every --container-image job fails with:
#   pyxis: mkdir: cannot create directory '/run/user/<uid>': Permission denied
export XDG_RUNTIME_DIR="/tmp/xdg-$(id -u)"
export ENROOT_RUNTIME_PATH="/tmp/enroot-$(id -u)/run"
export ENROOT_CACHE_PATH="/local/enroot-$(id -u)/cache"
export ENROOT_DATA_PATH="/local/enroot-$(id -u)/data"

# Pulling from the registry takes ~30 minutes and caches per-node. Import once
# to a .sqsh on shared storage (finetune/sbatch_import_image.sh) and point at
# the file: container startup then takes about 30 seconds on any node.
export DVIT_AUTOMODEL_IMAGE="${DVIT_AUTOMODEL_IMAGE:-$DVIT_SHARED/automodel-26.04.sqsh}"
export DVIT_VLLM_IMAGE="${DVIT_VLLM_IMAGE:-vllm/vllm-openai:latest}"

# --- Scratch ------------------------------------------------------------------
# /raid is NOT writable on this cluster despite the NVIDIA deck saying otherwise.
# /tmp and /local on a compute node each have ~3.2 TB and are node-local and
# non-persistent, which is what heavy I/O wants.
export DVIT_TMP_ROOT="${DVIT_TMP_ROOT:-/tmp}"

# --- Models -------------------------------------------------------------------
# Hugging Face names (for training):
export DVIT_TEACHER_MODEL="${DVIT_TEACHER_MODEL:-nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-BF16}"
export DVIT_STUDENT_MODEL="${DVIT_STUDENT_MODEL:-nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16}"
# build.nvidia.com endpoint names differ from the Hugging Face names — note the
# word order on nano. `python src/list_models.py nemotron` prints the live list.
export DVIT_TEACHER_API="${DVIT_TEACHER_API:-nvidia/nemotron-3-super-120b-a12b}"
export DVIT_STUDENT_API="${DVIT_STUDENT_API:-nvidia/nemotron-nano-3-30b-a3b}"

# --- Repositories -------------------------------------------------------------
export DVIT_REPO="${DVIT_REPO:-$DVIT_WORK/Dark-Vessel-Inspection-Triage}"
export DVIT_AUTOMODEL_REPO="${DVIT_AUTOMODEL_REPO:-$DVIT_WORK/Automodel}"

echo "DVIT_SHARED=$DVIT_SHARED"
echo "DVIT_WORK=$DVIT_WORK"
echo "HF_HOME=$HF_HOME"
echo "partition=$DVIT_PARTITION  account=$DVIT_ACCOUNT  gpus=$DVIT_GPUS_PER_NODE"
