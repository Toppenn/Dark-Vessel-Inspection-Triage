#!/bin/bash
#SBATCH -A omc-hackathon
#SBATCH -p hackathon
#SBATCH -J dvit-import
#SBATCH -N 1
#SBATCH -w dgx09
#SBATCH --cpus-per-task=16
#SBATCH -t 02:00:00
#SBATCH --output=logs/%x_%j.out
#SBATCH --error=logs/%x_%j.err
set -euo pipefail
source "${SLURM_SUBMIT_DIR}/finetune/cluster_env.sh"
cd "$DVIT_SHARED"
enroot import -o automodel-26.04.sqsh docker://nvcr.io#nvidia/nemo-automodel:26.04.00
ls -lh automodel-26.04.sqsh
