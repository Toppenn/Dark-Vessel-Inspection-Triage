#!/bin/bash
# Stage 2 — LoRA SFT of Nemotron-3-Nano-30B-A3B on ONE GPU.
#
# This is the variant that runs under the omc-team14 QOS (1 GPU for the whole
# team). It follows NVIDIA's nemotron_nano_v3_singlegpu_lora.yaml: ep_size 1,
# activation checkpointing, memory-efficient LoRA.
#
#   source finetune/cluster_env.sh
#   sbatch finetune/sbatch_sft_1gpu.sh
#
#SBATCH -A omc-hackathon
#SBATCH -p hackathon
#SBATCH -J dvit-sft-1gpu
#SBATCH -N 1
#SBATCH --gpus-per-node=1
#SBATCH --cpus-per-task=16
#SBATCH -t 08:00:00
#SBATCH --output=logs/%x_%j.out
#SBATCH --error=logs/%x_%j.err

set -euo pipefail
source "${SLURM_SUBMIT_DIR:-$(dirname "$0")/..}/finetune/cluster_env.sh"

# /raid is not writable on this cluster; /tmp on a compute node has ~3.2 TB.
export TMPDIR="${DVIT_TMP_ROOT}/dvit-${SLURM_JOB_ID}"
mkdir -p "$TMPDIR"
mkdir -p "${SLURM_SUBMIT_DIR}/logs"

RUN_DIR="$DVIT_WORK/runs/sft_${SLURM_JOB_ID}"
mkdir -p "$RUN_DIR"
sed "s|<<SET>>|$DVIT_DATA|g" \
    "${SLURM_SUBMIT_DIR}/finetune/nano_writer_lora_1gpu.yaml" > "$RUN_DIR/config.yaml"
sed -i "s|checkpoint_dir: .*|checkpoint_dir: $RUN_DIR/checkpoints|" "$RUN_DIR/config.yaml"
echo "[$(date)] config -> $RUN_DIR/config.yaml"

# Preflight: a minute here beats a flat loss curve in an hour. It loads the
# corpus through the same ChatDataset the recipe uses and prints the decoded
# supervised span, so a chat-template or masking mistake shows up now.
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
  bash -c "OMP_NUM_THREADS=8 MKL_NUM_THREADS=8 \
    torchrun --nproc_per_node=1 --nnodes=1 \
      -m nemo_automodel.cli.app $RUN_DIR/config.yaml"

echo "[$(date)] adapter in $RUN_DIR"
