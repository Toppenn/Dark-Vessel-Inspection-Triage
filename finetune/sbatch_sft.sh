#!/bin/bash
# Stage 2 — LoRA SFT of Nemotron-3-Nano-30B-A3B on one DGX B300 node.
#
#   source finetune/cluster_env.sh
#   sbatch finetune/sbatch_sft.sh
#
#SBATCH -A omc-hackathon
#SBATCH -p hackathon
#SBATCH -J dvit-sft
#SBATCH -N 1
#SBATCH --gpus-per-node=8
#SBATCH --ntasks-per-node=1
#SBATCH -t 04:00:00
#SBATCH --output=logs/%x_%j.out
#SBATCH --error=logs/%x_%j.err
#SBATCH --signal=B:USR1@300

set -euo pipefail
source "${SLURM_SUBMIT_DIR:-$(dirname "$0")/..}/finetune/cluster_env.sh"

export TMPDIR="/raid/${SLURM_JOB_ID}/tmp"
mkdir -p "$TMPDIR"

export MASTER_ADDR=$(scontrol show hostnames "$SLURM_JOB_NODELIST" | head -n 1)
export MASTER_PORT=${MASTER_PORT:-13742}

# Fill the <<SET>> placeholders into a job-local copy of the recipe, so the
# committed YAML stays path-free and the run keeps its exact config next to
# its checkpoints.
RUN_DIR="$DVIT_WORK/runs/sft_${SLURM_JOB_ID}"
mkdir -p "$RUN_DIR"
sed "s|<<SET>>|$DVIT_DATA|g" "$DVIT_REPO/finetune/nano_writer_lora.yaml" \
  > "$RUN_DIR/config.yaml"
sed -i "s|checkpoint_dir: $DVIT_DATA|checkpoint_dir: $RUN_DIR|" "$RUN_DIR/config.yaml"
echo "[$(date)] config -> $RUN_DIR/config.yaml"

# Preflight: a minute here beats a flat loss curve in an hour.
srun --overlap --ntasks=1 \
  --container-image="$DVIT_AUTOMODEL_IMAGE" \
  --container-mounts="$DVIT_SHARED:$DVIT_SHARED,$DVIT_AUTOMODEL_REPO:/opt/Automodel" \
  --container-workdir="$DVIT_REPO" \
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
      --nproc_per_node=${DVIT_GPUS_PER_NODE} \
      --nnodes=${SLURM_NNODES:-1} \
      --rdzv_backend=c10d \
      --rdzv_endpoint=${MASTER_ADDR}:${MASTER_PORT} \
      -m nemo_automodel.cli.app $RUN_DIR/config.yaml"

echo "[$(date)] adapter in $RUN_DIR"
