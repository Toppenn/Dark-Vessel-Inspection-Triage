#!/bin/bash
# Stage 2 — LoRA SFT of Nemotron-3-Nano-30B-A3B on a full 8-GPU node.
#
# NOT usable under the current omc-team14 QOS, which caps the whole team at one
# GPU (see CLUSTER_NOTES.md). Kept because it is the right shape if the cap is
# raised, or on any cluster that gives you a node. Use sbatch_sft_1gpu.sh here.
#
#   source finetune/cluster_env.sh
#   DVIT_GPUS_PER_NODE=8 sbatch finetune/sbatch_sft_8gpu.sh
#
#SBATCH -A omc-hackathon
#SBATCH -p hackathon
#SBATCH -J dvit-sft-8gpu
#SBATCH -N 1
#SBATCH --gpus-per-node=8
#SBATCH --ntasks-per-node=1
#SBATCH -t 04:00:00
#SBATCH --output=logs/%x_%j.out
#SBATCH --error=logs/%x_%j.err
#SBATCH --signal=B:USR1@300

set -euo pipefail
source "${SLURM_SUBMIT_DIR:-$(dirname "$0")/..}/finetune/cluster_env.sh"

# /raid is not writable on this cluster; /tmp on a compute node has ~3.2 TB.
export TMPDIR="${DVIT_TMP_ROOT}/dvit-${SLURM_JOB_ID}"
mkdir -p "$TMPDIR"
mkdir -p "${SLURM_SUBMIT_DIR}/logs"

export MASTER_ADDR=$(scontrol show hostnames "$SLURM_JOB_NODELIST" | head -n 1)
export MASTER_PORT=${MASTER_PORT:-13742}

RUN_DIR="$DVIT_WORK/runs/sft_${SLURM_JOB_ID}"
mkdir -p "$RUN_DIR"
sed "s|<<SET>>|$DVIT_DATA|g" \
    "${SLURM_SUBMIT_DIR}/finetune/nano_writer_lora_8gpu.yaml" > "$RUN_DIR/config.yaml"
sed -i "s|checkpoint_dir: .*|checkpoint_dir: $RUN_DIR/checkpoints|" "$RUN_DIR/config.yaml"
echo "[$(date)] config -> $RUN_DIR/config.yaml"

srun --overlap --ntasks=1 \
  --container-image="$DVIT_AUTOMODEL_IMAGE" \
  --container-mounts="$DVIT_SHARED:$DVIT_SHARED,$DVIT_AUTOMODEL_REPO:/opt/Automodel" \
  --container-workdir="${SLURM_SUBMIT_DIR}" \
  --export=ALL \
  python finetune/preflight_dataset.py \
    --path "$DVIT_DATA/sft/train.jsonl" \
    --model "$DVIT_STUDENT_MODEL" \
    --seq-length 16384

srun \
  --container-image="$DVIT_AUTOMODEL_IMAGE" \
  --container-mounts="$DVIT_SHARED:$DVIT_SHARED,$DVIT_AUTOMODEL_REPO:/opt/Automodel" \
  --container-workdir=/opt/Automodel \
  --no-container-mount-home \
  --export=ALL \
  bash -c "torchrun \
      --nproc_per_node=8 \
      --nnodes=\${SLURM_NNODES:-1} \
      --rdzv_backend=c10d \
      --rdzv_endpoint=${MASTER_ADDR}:${MASTER_PORT} \
      -m nemo_automodel.cli.app $RUN_DIR/config.yaml"

echo "[$(date)] adapter in $RUN_DIR"
