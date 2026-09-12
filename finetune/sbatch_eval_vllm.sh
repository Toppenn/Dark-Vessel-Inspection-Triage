#!/bin/bash
# Stage 3 (self-hosted variant) — base vs adapter, both served locally with
# vLLM in one allocation so the numbers come from the same node and stack.
#
# Needs enough GPUs to serve Nemotron-3-Nano (~60 GB BF16). Under the current
# omc-team14 QOS (1 GPU) a single B300 at 275 GB is sufficient, so this can run
# with DVIT_GPUS_PER_NODE=1. Use sbatch_eval_api.sh for the base-model arm if
# you would rather not spend the GPU.
#
#   source finetune/cluster_env.sh
#   RUN_DIR=$DVIT_WORK/runs/sft_123456 sbatch finetune/sbatch_eval_vllm.sh
#
#SBATCH -A omc-hackathon
#SBATCH -p hackathon
#SBATCH -J dvit-eval-vllm
#SBATCH -N 1
#SBATCH --gpus-per-node=1
#SBATCH --ntasks-per-node=1
#SBATCH -t 04:00:00
#SBATCH --output=logs/%x_%j.out
#SBATCH --error=logs/%x_%j.err

set -euo pipefail
source "${SLURM_SUBMIT_DIR:-$(dirname "$0")/..}/finetune/cluster_env.sh"

# /raid is not writable on this cluster; /tmp on a compute node has ~3.2 TB.
export TMPDIR="${DVIT_TMP_ROOT}/dvit-${SLURM_JOB_ID}"
mkdir -p "$TMPDIR"
mkdir -p "${SLURM_SUBMIT_DIR}/logs"
cd "${SLURM_SUBMIT_DIR}"

RUN_DIR="${RUN_DIR:?set RUN_DIR to the sbatch_sft_1gpu.sh output directory}"
PORT="${PORT:-8000}"
N="${N:-40}"
SCENES="${SCENES:-$DVIT_DATA/scenes_holdout.jsonl}"
TP="${DVIT_GPUS_PER_NODE}"

# AutoModel with `save_consolidated: final` writes a consolidated safetensors
# checkpoint. Depending on the version this is either the merged model or the
# base plus an adapter directory — look before assuming, they are served
# differently.
echo "checkpoint contents:"; ls -la "$RUN_DIR"/checkpoints/* 2>/dev/null | head -40

serve_and_eval () {
  local MODEL_PATH="$1" LABEL="$2" OUT="$3"; shift 3
  echo "[$(date)] serving $MODEL_PATH as '$LABEL'"
  srun --overlap --ntasks=1 \
    --container-image="$DVIT_VLLM_IMAGE" \
    --container-mounts="$DVIT_SHARED:$DVIT_SHARED" \
    --export=ALL \
    bash -c "vllm serve '$MODEL_PATH' \
        --tensor-parallel-size $TP \
        --max-model-len 65536 --port $PORT \
        --served-model-name evalmodel --trust-remote-code $*" &
  local PID=$!
  for i in $(seq 1 180); do
    curl -sf "http://127.0.0.1:$PORT/v1/models" >/dev/null 2>&1 && break
    kill -0 "$PID" 2>/dev/null || { echo "vLLM died"; return 1; }
    sleep 10
  done
  # Analyst held fixed at the teacher so the number measures the WRITER only.
  NVIDIA_BASE_URL="http://127.0.0.1:$PORT/v1" NVIDIA_API_KEY=local \
  ANALYST_MODEL_OVERRIDE="$DVIT_TEACHER_API" \
  "$DVIT_PY" finetune/eval_live.py \
      --scenes "$SCENES" \
      --model evalmodel --label "$LABEL" --n "$N" --workers 8 \
      --out "$OUT"
  kill "$PID" 2>/dev/null || true
  sleep 30
}

# 1. Baseline: the small model as it ships.
serve_and_eval "$DVIT_STUDENT_MODEL" "nano (base)" "$DVIT_DATA/eval_nano_base_local.json"

# 2. After the fine-tune. If the checkpoint is a merged model, this serves it
#    directly. If it is an adapter, serve the base with
#    --enable-lora --lora-modules evalmodel=<adapter dir> instead, and confirm
#    your vLLM build supports LoRA on this hybrid Mamba-2/MoE architecture — if
#    it does not, merge the adapter first.
CKPT="$(ls -d "$RUN_DIR"/checkpoints/*/ 2>/dev/null | tail -1)"
serve_and_eval "$CKPT" "nano (LoRA)" "$DVIT_DATA/eval_nano_lora.json"

"$DVIT_PY" finetune/eval_live.py --compare \
    "$DVIT_DATA/eval_nano_base_local.json" "$DVIT_DATA/eval_nano_lora.json"
