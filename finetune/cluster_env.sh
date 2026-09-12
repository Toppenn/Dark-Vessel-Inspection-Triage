#!/bin/bash
# Cluster settings for Curiosity v2. Source this from every job script and
# from your interactive shell:  source finetune/cluster_env.sh
#
# Everything cluster-specific lives here so nothing else in finetune/ has to
# know what machine it is on.

# --- Things to check once, on the login node, and then set --------------------
# sinfo -o "%P %l %D %G"        -> partitions, time limits, GPUs per node
# sacctmgr show assoc user=$USER format=account,partition   -> your account
# scontrol show partition       -> per-partition limits
export DVIT_ACCOUNT="${DVIT_ACCOUNT:-}"          # leave empty if -A is not required
export DVIT_PARTITION="${DVIT_PARTITION:-batch}" # <-- CONFIRM with sinfo
export DVIT_GPUS_PER_NODE="${DVIT_GPUS_PER_NODE:-8}"

# --- Storage ------------------------------------------------------------------
# $HOME is 50 GB. A single BF16 Nemotron-3-Nano checkpoint is ~60 GB and Super
# is ~240 GB, so the Hugging Face cache MUST NOT live in $HOME or the first
# download will fill the quota and fail halfway. The team shared folder has
# 300 GB; find yours and set DVIT_SHARED.
#
#   ls -ld /shared/* /project/* /team/* 2>/dev/null    # <-- CONFIRM the path
export DVIT_SHARED="${DVIT_SHARED:-$HOME/shared}"     # <-- SET THIS
export DVIT_WORK="${DVIT_WORK:-$DVIT_SHARED/dvit}"
export DVIT_DATA="${DVIT_DATA:-$DVIT_WORK/data}"

export HF_HOME="${HF_HOME:-$DVIT_SHARED/hf}"
export HF_HUB_CACHE="$HF_HOME/hub"
export HUGGINGFACE_HUB_CACHE="$HF_HUB_CACHE"
export TRANSFORMERS_CACHE="$HF_HOME"
# Set your token if you have one; the Nemotron Open Model License may require
# accepting terms on the model page first.
export HF_TOKEN="${HF_TOKEN:-}"

mkdir -p "$DVIT_WORK" "$DVIT_DATA" "$HF_HOME" "$DVIT_WORK/logs" 2>/dev/null

# --- Container images ---------------------------------------------------------
# ASK THE MENTORS which images are cached locally for the B300 nodes; pulling a
# multi-GB image on every job is slow and the Blackwell-Ultra-compatible tags
# move fast. These are the upstream defaults.
export DVIT_AUTOMODEL_IMAGE="${DVIT_AUTOMODEL_IMAGE:-nvcr.io/nvidia/nemo-automodel:26.04.00}"
export DVIT_VLLM_IMAGE="${DVIT_VLLM_IMAGE:-vllm/vllm-openai:latest}"

# Enroot/pyxis caches the converted image here; keep it off $HOME.
export ENROOT_CACHE_PATH="${ENROOT_CACHE_PATH:-$DVIT_SHARED/enroot/cache}"
export ENROOT_DATA_PATH="${ENROOT_DATA_PATH:-$DVIT_SHARED/enroot/data}"
mkdir -p "$ENROOT_CACHE_PATH" "$ENROOT_DATA_PATH" 2>/dev/null

# --- Models -------------------------------------------------------------------
export DVIT_TEACHER_MODEL="${DVIT_TEACHER_MODEL:-nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-BF16}"
export DVIT_STUDENT_MODEL="${DVIT_STUDENT_MODEL:-nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16}"

# --- Repo ---------------------------------------------------------------------
export DVIT_REPO="${DVIT_REPO:-$DVIT_WORK/Dark-Vessel-Inspection-Triage}"
export DVIT_AUTOMODEL_REPO="${DVIT_AUTOMODEL_REPO:-$DVIT_WORK/Automodel}"

echo "DVIT_SHARED=$DVIT_SHARED"
echo "DVIT_WORK=$DVIT_WORK"
echo "HF_HOME=$HF_HOME"
echo "partition=$DVIT_PARTITION  gpus/node=$DVIT_GPUS_PER_NODE"

