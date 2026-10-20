# Docker layer adding SedonaDB to the gdal-r-python chain.
# This is the Setonix-friendly path: build/push in CI, then on Setonix
#   module load singularity/<version>-nompi
#   singularity pull sedonadb.sif docker://ghcr.io/mdsumner/gdal-sedonadb:latest
# (no on-system builds are possible on Setonix; pull converts to SIF)

FROM ghcr.io/mdsumner/gdal-r-python:latest

RUN python3 -m pip install --no-cache-dir --break-system-packages \
        sedonadb \
        sedonadb-zarr \
        sedonadb-expr

# acceptance test baked into the build: GDAL first, pyarrow second
# (that ordering is the LD_LIBRARY_PATH collision path)
RUN python3 -c "from osgeo import gdal; import pyarrow, sedonadb; \
        print(gdal.__version__, pyarrow.__version__)"
