#!/bin/bash
# Stage 3 — the before/after measurement, on held-out scenes.
#
# Serves one model, runs eval_live.py against it, tears it down, repeats. Two
# passes in one allocation so the numbers come from the same node, the same
# night and the same data.
#
#   source finetune/cluster_env.sh
#   RUN_DIR=$DVIT_WORK/runs/sft_123456 sbatch finetune/sbatch_eval.sh
#
#SBATCH -A omc-hackathon
#SBATCH -p hackathon
#SBATCH -J dvit-eval
#SBATCH -N 1
#SBATCH --gpus-per-node=8
#SBATCH --ntasks-per-node=1
#SBATCH -t 03:00:00
#SBATCH --output=logs/%x_%j.out
#SBATCH --error=logs/%x_%j.err

set -euo pipefail
source "${SLURM_SUBMIT_DIR:-$(dirname "$0")/..}/finetune/cluster_env.sh"
export TMPDIR="/raid/${SLURM_JOB_ID}/tmp"; mkdir -p "$TMPDIR"

RUN_DIR="${RUN_DIR:?set RUN_DIR to the sbatch_sft.sh output directory}"
PORT="${PORT:-8000}"
N="${N:-40}"
cd "$DVIT_REPO"

# AutoModel with `save_consolidated: final` writes a consolidated safetensors
# checkpoint. Depending on the version this is either the merged model or the
# base plus an adapter directory — check what is actually there before
# assuming, because the two are served differently.
echo "checkpoint contents:"; ls -la "$RUN_DIR"/checkpoints/* 2>/dev/null | head -40

serve_and_eval () {
  local MODEL_PATH="$1" LABEL="$2" OUT="$3"; shift 3
  echo "[$(date)] serving $MODEL_PATH as '$LABEL'"
  srun --overlap --ntasks=1 \
    --container-image="$DVIT_VLLM_IMAGE" \
    --container-mounts="$DVIT_SHARED:$DVIT_SHARED" \
    --export=ALL \
    bash -c "vllm serve '$MODEL_PATH' \
        --tensor-parallel-size $DVIT_GPUS_PER_NODE \
        --max-model-len 65536 --port $PORT \
        --served-model-name evalmodel --trust-remote-code $*" &
  local PID=$!
  for i in $(seq 1 180); do
    curl -sf "http://127.0.0.1:$PORT/v1/models" >/dev/null 2>&1 && break
    kill -0 "$PID" 2>/dev/null || { echo "vLLM died"; return 1; }
    sleep 10
  done
  NVIDIA_BASE_URL="http://127.0.0.1:$PORT/v1" NVIDIA_API_KEY=local \
  python finetune/eval_live.py \
      --scenes "$DVIT_DATA/scenes.jsonl" \
      --held-out "$DVIT_DATA/sft/validation.jsonl" \
      --model evalmodel --label "$LABEL" --n "$N" --workers 8 \
      --out "$OUT"
  kill "$PID" 2>/dev/null || true
  sleep 30
}

# 1. Baseline: the small model as it ships.
serve_and_eval "$DVIT_STUDENT_MODEL" "nano (base)" "$DVIT_DATA/eval_nano_base.json"

# 2. After the fine-tune. If the checkpoint is a merged model, point at it
#    directly (below). If it is an adapter, serve the base with
#    --enable-lora --lora-modules evalmodel=$RUN_DIR/checkpoints/... instead,
#    and confirm your vLLM build supports LoRA on this hybrid-MoE
#    architecture — if it does not, merge the adapter first.
CKPT="$(ls -d "$RUN_DIR"/checkpoints/*/ 2>/dev/null | tail -1)"
serve_and_eval "$CKPT" "nano (LoRA)" "$DVIT_DATA/eval_nano_lora.json"

python finetune/eval_live.py --compare \
    "$DVIT_DATA/eval_nano_base.json" "$DVIT_DATA/eval_nano_lora.json"
