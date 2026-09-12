#!/bin/bash
# Import the AutoModel container to a .sqsh on shared storage, once.
#
# Pulling nvcr.io/nvidia/nemo-automodel from the registry takes ~30 minutes and
# enroot caches it per-node, so every job on a new node pays again. A .sqsh on
# /storage makes container startup about 30 seconds anywhere.
#
# Pinned to a node that already has the layers in its enroot cache, if you know
# one — otherwise drop the -w line and let Slurm choose.
#
#   source finetune/cluster_env.sh
#   sbatch finetune/sbatch_import_image.sh
#
#SBATCH -A omc-hackathon
#SBATCH -p hackathon
#SBATCH -J dvit-import
#SBATCH -N 1
#SBATCH --cpus-per-task=16
#SBATCH -t 02:00:00
#SBATCH --output=logs/%x_%j.out
#SBATCH --error=logs/%x_%j.err

set -euo pipefail
source "${SLURM_SUBMIT_DIR:-$(dirname "$0")/..}/finetune/cluster_env.sh"
mkdir -p "${SLURM_SUBMIT_DIR}/logs"
cd "$DVIT_SHARED"

IMAGE="${IMAGE:-docker://nvcr.io#nvidia/nemo-automodel:26.04.00}"
OUT="${OUT:-automodel-26.04.sqsh}"

echo "[$(date)] importing $IMAGE -> $DVIT_SHARED/$OUT on $(hostname)"
enroot import -o "$OUT" "$IMAGE"
ls -lh "$OUT"
echo "[$(date)] now set DVIT_AUTOMODEL_IMAGE=$DVIT_SHARED/$OUT (cluster_env.sh already does)"
