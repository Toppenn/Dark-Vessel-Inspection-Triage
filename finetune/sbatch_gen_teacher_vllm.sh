#!/bin/bash
# Stage 1 (self-hosted variant) — serve the teacher on one node with vLLM and
# generate the corpus against it, in the same job.
#
# NOT usable under the current omc-team14 QOS, which caps the whole team at one
# GPU: Super-120B BF16 is ~240 GB and needs a node. Use
# sbatch_gen_teacher_api.sh here, which is CPU-only and costs no GPU at all.
# Kept because self-hosting is the deployment argument the project rests on, and
# this is the shape it takes.
#
#   source finetune/cluster_env.sh
#   DVIT_GPUS_PER_NODE=8 sbatch finetune/sbatch_gen_teacher_vllm.sh
#
#SBATCH -A omc-hackathon
#SBATCH -p hackathon
#SBATCH -J dvit-teacher-vllm
#SBATCH -N 1
#SBATCH --gpus-per-node=8
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

N_SCENES="${N_SCENES:-400}"
ATTEMPTS="${ATTEMPTS:-3}"
WORKERS="${WORKERS:-16}"
PORT="${PORT:-8000}"
TP="${DVIT_GPUS_PER_NODE}"

echo "[$(date)] node=$(hostname) job=$SLURM_JOB_ID tp=$TP"
nvidia-smi --query-gpu=index,name,memory.total --format=csv

# --- 0. Scenes (CPU only, seconds) -------------------------------------------
"$DVIT_PY" finetune/surface_vocab.py --n 60 --out "$DVIT_DATA/surface_vocab.jsonl" || \
  echo "[warn] Data Designer unavailable; using the static surface pool"
"$DVIT_PY" finetune/scene_factory.py --n "$N_SCENES" \
  --vocab "$DVIT_DATA/surface_vocab.jsonl" \
  --out "$DVIT_DATA/scenes.jsonl"

# --- 1. Serve the teacher -----------------------------------------------------
srun --overlap --ntasks=1 \
  --container-image="$DVIT_VLLM_IMAGE" \
  --container-mounts="$DVIT_SHARED:$DVIT_SHARED" \
  --container-workdir="${SLURM_SUBMIT_DIR}" \
  --export=ALL \
  bash -c "vllm serve '$DVIT_TEACHER_MODEL' \
      --tensor-parallel-size $TP \
      --max-model-len 65536 \
      --port $PORT \
      --served-model-name teacher \
      --trust-remote-code" &
VLLM_PID=$!
cleanup() { kill "$VLLM_PID" 2>/dev/null || true; }
trap cleanup EXIT

# --- 2. Wait for the endpoint -------------------------------------------------
echo "[$(date)] waiting for vLLM (first run downloads ~240 GB to $HF_HOME)"
for i in $(seq 1 240); do
  if curl -sf "http://127.0.0.1:$PORT/v1/models" >/dev/null 2>&1; then
    echo "[$(date)] endpoint up after ${i}0s"; break
  fi
  kill -0 "$VLLM_PID" 2>/dev/null || { echo "vLLM died during startup"; exit 1; }
  sleep 10
done
curl -sf "http://127.0.0.1:$PORT/v1/models" >/dev/null || { echo "endpoint never came up"; exit 1; }

# --- 3. Generate --------------------------------------------------------------
export NVIDIA_BASE_URL="http://127.0.0.1:$PORT/v1"
export NVIDIA_API_KEY="local"
export MAX_TOKENS="${MAX_TOKENS:-16000}"

"$DVIT_PY" finetune/gen_teacher.py \
  --scenes "$DVIT_DATA/scenes.jsonl" \
  --out "$DVIT_DATA/sft_raw.jsonl" \
  --model teacher \
  --attempts "$ATTEMPTS" \
  --workers "$WORKERS" \
  --strict

# --- 4. Curate ----------------------------------------------------------------
"$DVIT_PY" finetune/curate.py \
  --in "$DVIT_DATA/sft_raw.jsonl" \
  --outdir "$DVIT_DATA/sft" \
  --agent writer

echo "[$(date)] done. Corpus in $DVIT_DATA/sft"
