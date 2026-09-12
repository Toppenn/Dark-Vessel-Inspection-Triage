#!/bin/bash
#SBATCH -A omc-hackathon
#SBATCH -p hackathon
#SBATCH -J dvit-eval-api
#SBATCH -N 1
#SBATCH --cpus-per-task=4
#SBATCH -t 04:00:00
#SBATCH --output=logs/%x_%j.out
#SBATCH --error=logs/%x_%j.err
set -euo pipefail
source "${SLURM_SUBMIT_DIR}/finetune/cluster_env.sh"
cd "${SLURM_SUBMIT_DIR}"
: "${NVIDIA_API_KEY:?}"
export NVIDIA_BASE_URL="https://integrate.api.nvidia.com/v1"
# Analyst held fixed at the teacher so the number measures the WRITER only.
export ANALYST_MODEL_OVERRIDE="nvidia/nemotron-3-super-120b-a12b"
"$DVIT_PY" finetune/eval_live.py \
    --scenes "$DVIT_DATA/scenes_holdout.jsonl" \
    --model "${EVAL_MODEL:-nvidia/nemotron-nano-3-30b-a3b}" \
    --label "${EVAL_LABEL:-nano (base)}" \
    --n 40 --workers 4 \
    --out "$DVIT_DATA/${EVAL_OUT:-eval_nano_base}.json"
