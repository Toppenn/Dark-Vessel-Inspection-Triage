#!/bin/bash
# Stage 1 (default variant) — teacher corpus via build.nvidia.com.
#
# CPU-only. Teacher generation is API-bound, not compute-bound, so it never
# needed a GPU — and asking for none means the job can also land on the idle
# nodes whose GPU GRES is unregistered (dgx01-04, dgx10). Under a 1-GPU team
# cap that matters: this stage costs you nothing.
#
#   source finetune/cluster_env.sh
#   export NVIDIA_API_KEY='nvapi-...'
#   sbatch --export=ALL,NVIDIA_API_KEY finetune/sbatch_gen_teacher_api.sh
#
# Tunables:  N_SCENES (default 400)   WORKERS (default 8)   ATTEMPTS (default 3)
#
#SBATCH -A omc-hackathon
#SBATCH -p hackathon
#SBATCH -J dvit-teacher-api
#SBATCH -N 1
#SBATCH --cpus-per-task=8
#SBATCH -t 08:00:00
#SBATCH --output=logs/%x_%j.out
#SBATCH --error=logs/%x_%j.err

set -euo pipefail
source "${SLURM_SUBMIT_DIR:-$(dirname "$0")/..}/finetune/cluster_env.sh"
mkdir -p "${SLURM_SUBMIT_DIR}/logs"
cd "${SLURM_SUBMIT_DIR:-$DVIT_REPO}"

: "${NVIDIA_API_KEY:?export NVIDIA_API_KEY and pass --export=ALL,NVIDIA_API_KEY}"
export NVIDIA_BASE_URL="https://integrate.api.nvidia.com/v1"

"$DVIT_PY" finetune/scene_factory.py \
    --n "${N_SCENES:-400}" \
    --out "$DVIT_DATA/scenes.jsonl"

"$DVIT_PY" finetune/gen_teacher.py \
    --scenes "$DVIT_DATA/scenes.jsonl" \
    --out "$DVIT_DATA/sft_raw.jsonl" \
    --model "${TEACHER:-$DVIT_TEACHER_API}" \
    --attempts "${ATTEMPTS:-3}" \
    --workers "${WORKERS:-8}" \
    --strict

"$DVIT_PY" finetune/curate.py \
    --in "$DVIT_DATA/sft_raw.jsonl" \
    --outdir "$DVIT_DATA/sft" \
    --agent writer

echo "[$(date)] corpus in $DVIT_DATA/sft"
