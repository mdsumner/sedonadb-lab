#!/bin/bash
#SBATCH --job-name=sedonadb-chunks
#SBATCH --array=0-15
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=16G
#SBATCH --time=01:00:00
#SBATCH --output=logs/%x-%a.out

# One SedonaDB engine per array task; no server, no coordination.
# Each task is an independent in-process engine reading only the
# chunk rows in its window. Concatenate/union the parquet parts after.

set -euo pipefail

SIF=${SIF:-sedonadb.sif}
module load singularity/*-nompi 2>/dev/null || true   # Setonix; no-op elsewhere
ZARR_URL=${ZARR_URL:?set ZARR_URL, e.g. s3://bucket/path.zarr or https://...}
ARRAY_NAME=${ARRAY_NAME:?set ARRAY_NAME, the zarr array/variable to read}
OUTDIR=${OUTDIR:-$PWD/out}
N_TASKS=$(( SLURM_ARRAY_TASK_MAX + 1 ))

mkdir -p "$OUTDIR" logs

# --cleanenv keeps host python/R env vars out; pass through only what
# the worker needs. Add -B for scratch or data mounts as required,
# e.g. -B /scratch,/g/data on gadi-style systems.
${CONTAINER_EXEC:-singularity} exec --cleanenv \
    --env "TOKIO_WORKER_THREADS=${SLURM_CPUS_PER_TASK}" \
    --env "RAYON_NUM_THREADS=${SLURM_CPUS_PER_TASK}" \
    --env "AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID:-}" \
    --env "AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY:-}" \
    --env "AWS_ENDPOINT_URL=${AWS_ENDPOINT_URL:-}" \
    -B "$OUTDIR" \
    "$SIF" \
    python3 worker.py \
        "$SLURM_ARRAY_TASK_ID" "$N_TASKS" \
        "$ZARR_URL" "$ARRAY_NAME" "$OUTDIR"
