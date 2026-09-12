#!/bin/bash
# Stage 1 — serve the teacher on one node and generate the corpus against it.
#
# Serving and generating in the SAME job avoids every cross-node networking
# question: vLLM binds localhost, the generator talks to localhost, and the
# node is released when both are done.
#
#   source finetune/cluster_env.sh
#   sbatch finetune/sbatch_gen_teacher.sh
#
#SBATCH -A omc-hackathon
#SBATCH -p hackathon
#SBATCH -J dvit-teacher
#SBATCH -N 1
#SBATCH --gpus-per-node=8
#SBATCH --ntasks-per-node=1
#SBATCH -t 04:00:00
#SBATCH --output=logs/%x_%j.out
#SBATCH --error=logs/%x_%j.err

set -euo pipefail
source "${SLURM_SUBMIT_DIR:-$(dirname "$0")/..}/finetune/cluster_env.sh"

# Policy: /tmp on a compute node is not persistent and NSight's global lock
# lives there; the cluster guide points TMPDIR at the node-local RAID.
export TMPDIR="/raid/${SLURM_JOB_ID}/tmp"
mkdir -p "$TMPDIR"

N_SCENES="${N_SCENES:-400}"
ATTEMPTS="${ATTEMPTS:-3}"
WORKERS="${WORKERS:-16}"
PORT="${PORT:-8000}"

echo "[$(date)] node=$(hostname) job=$SLURM_JOB_ID"
nvidia-smi --query-gpu=index,name,memory.total --format=csv

# --- 0. Scenes (CPU only, seconds) -------------------------------------------
cd "$DVIT_REPO"
python finetune/surface_vocab.py --n 60 --out "$DVIT_DATA/surface_vocab.jsonl" || \
  echo "[warn] Data Designer unavailable; using the static surface pool"
python finetune/scene_factory.py --n "$N_SCENES" \
  --vocab "$DVIT_DATA/surface_vocab.jsonl" \
  --out "$DVIT_DATA/scenes.jsonl"

# --- 1. Serve the teacher -----------------------------------------------------
# Started under enroot/pyxis. If your site prefers apptainer, replace the srun
# block with:  apptainer exec --nv docker://$DVIT_VLLM_IMAGE vllm serve ...
srun --overlap --ntasks=1 \
  --container-image="$DVIT_VLLM_IMAGE" \
  --container-mounts="$DVIT_SHARED:$DVIT_SHARED" \
  --container-workdir="$DVIT_REPO" \
  --export=ALL \
  bash -c "vllm serve '$DVIT_TEACHER_MODEL' \
      --tensor-parallel-size $DVIT_GPUS_PER_NODE \
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
  if ! kill -0 "$VLLM_PID" 2>/dev/null; then
    echo "[$(date)] vLLM died during startup — see the .err file"; exit 1
  fi
  sleep 10
done
curl -sf "http://127.0.0.1:$PORT/v1/models" || { echo "endpoint never came up"; exit 1; }

# --- 3. Generate --------------------------------------------------------------
export NVIDIA_BASE_URL="http://127.0.0.1:$PORT/v1"
export NVIDIA_API_KEY="local"
export MAX_TOKENS="${MAX_TOKENS:-16000}"

python finetune/gen_teacher.py \
  --scenes "$DVIT_DATA/scenes.jsonl" \
  --out "$DVIT_DATA/sft_raw.jsonl" \
  --model teacher \
  --attempts "$ATTEMPTS" \
  --workers "$WORKERS" \
  --strict

# --- 4. Curate ----------------------------------------------------------------
python finetune/curate.py \
  --in "$DVIT_DATA/sft_raw.jsonl" \
  --outdir "$DVIT_DATA/sft" \
  --agent writer

echo "[$(date)] done. Corpus in $DVIT_DATA/sft"
