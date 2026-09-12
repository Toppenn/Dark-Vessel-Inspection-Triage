#!/bin/bash
# Stage 3 (default variant) — live-model evaluation via build.nvidia.com.
#
# CPU-only, so the baseline arm costs no GPU. Runs on scenes_holdout.jsonl,
# which scene_factory generates from seed 10000 — disjoint by construction from
# the training seeds (0..N), so no leakage regardless of how curate.py split.
#
#   source finetune/cluster_env.sh
#   "$DVIT_PY" finetune/scene_factory.py --n 40 --seed 10000 \
#       --out $DVIT_DATA/scenes_holdout.jsonl
#   sbatch --export=ALL,NVIDIA_API_KEY finetune/sbatch_eval_api.sh
#
# Tunables:  EVAL_MODEL   EVAL_LABEL   EVAL_OUT   N (default 40)
#
#SBATCH -A omc-hackathon
#SBATCH -p hackathon
#SBATCH -J dvit-eval-api
#SBATCH -N 1
#SBATCH --cpus-per-task=4
#SBATCH -t 04:00:00
#SBATCH --output=logs/%x_%j.out
#SBATCH --error=logs/%x_%j.err

set -euo pipefail
source "${SLURM_SUBMIT_DIR:-$(dirname "$0")/..}/finetune/cluster_env.sh"
mkdir -p "${SLURM_SUBMIT_DIR}/logs"
cd "${SLURM_SUBMIT_DIR}"

: "${NVIDIA_API_KEY:?export NVIDIA_API_KEY and pass --export=ALL,NVIDIA_API_KEY}"
export NVIDIA_BASE_URL="https://integrate.api.nvidia.com/v1"

# The analyst is held fixed at the teacher so the number measures the WRITER
# alone. Without this the table conflates two models changing at once.
export ANALYST_MODEL_OVERRIDE="$DVIT_TEACHER_API"

"$DVIT_PY" finetune/eval_live.py \
    --scenes "$DVIT_DATA/scenes_holdout.jsonl" \
    --model "${EVAL_MODEL:-$DVIT_STUDENT_API}" \
    --label "${EVAL_LABEL:-nano (base)}" \
    --n "${N:-40}" --workers 4 \
    --out "$DVIT_DATA/${EVAL_OUT:-eval_nano_base}.json"
