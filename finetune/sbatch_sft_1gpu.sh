#!/bin/bash
# Stage 2 on ONE GPU. Based on NVIDIA's nemotron_nano_v3_singlegpu_lora.yaml.
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
export TMPDIR="/raid/${SLURM_JOB_ID}/tmp"; mkdir -p "$TMPDIR" || export TMPDIR=/tmp
RUN_DIR="$DVIT_WORK/runs/sft_${SLURM_JOB_ID}"; mkdir -p "$RUN_DIR"
sed "s|<<SET>>|$DVIT_DATA|g" "${SLURM_SUBMIT_DIR}/finetune/nano_writer_lora_1gpu.yaml" > "$RUN_DIR/config.yaml"
sed -i "s|checkpoint_dir: .*|checkpoint_dir: $RUN_DIR/checkpoints|" "$RUN_DIR/config.yaml"
srun --container-image="$DVIT_AUTOMODEL_IMAGE" \
  --container-mounts="$DVIT_SHARED:$DVIT_SHARED,$DVIT_AUTOMODEL_REPO:/opt/Automodel" \
  --container-workdir=/opt/Automodel --no-container-mount-home --export=ALL \
  bash -c "OMP_NUM_THREADS=8 MKL_NUM_THREADS=8 \
    torchrun --nproc_per_node=1 --nnodes=1 \
    -m nemo_automodel.cli.app $RUN_DIR/config.yaml"
echo "adapter in $RUN_DIR"
