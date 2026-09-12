#!/bin/bash
# Stage 1, CPU-only: teacher via build.nvidia.com. No GPU, so it can schedule
# on the GRES-less idle nodes. Set NVIDIA_API_KEY before sbatch.
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
cd "${SLURM_SUBMIT_DIR:-$DVIT_REPO}"
: "${NVIDIA_API_KEY:?export NVIDIA_API_KEY before sbatch}"
export NVIDIA_BASE_URL="https://integrate.api.nvidia.com/v1"

"$DVIT_PY" finetune/scene_factory.py --n "${N_SCENES:-300}" --out "$DVIT_DATA/scenes.jsonl"
"$DVIT_PY" finetune/gen_teacher.py \
    --scenes "$DVIT_DATA/scenes.jsonl" --out "$DVIT_DATA/sft_raw.jsonl" \
    --model "${TEACHER:-nvidia/nemotron-3-super-120b-a12b}" \
    --attempts 3 --workers "${WORKERS:-4}" --strict
"$DVIT_PY" finetune/curate.py --in "$DVIT_DATA/sft_raw.jsonl" \
    --outdir "$DVIT_DATA/sft" --agent writer
