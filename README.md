# sedonadb-hpc

Reference kit for running SedonaDB (Apache Sedona's embedded, single-node
engine) against Zarr datacubes on slurm HPC, containerized via Apptainer
built from the hypertidy gdal-r-python image chain.

SedonaDB is an in-process engine (DataFusion + Arrow): no server, no
daemon. One slurm task = one engine using that allocation's cores.
Multi-node scaling is external orchestration; the one-row-per-chunk model
shards naturally by chunk/dimension ranges.

## Files

- `Dockerfile`       Docker layer on gdal-r-python (the Setonix path).
- `sedonadb.def`     Apptainer definition (for laptop/Nimbus builds).
- `verify_zarr.py`   Generate a known-good fixture, or 3-stage check any
                     store: enumerate -> slice -> decode.
- `worker.py`        One engine per array task; filters chunk rows by
                     spatial window; writes a parquet part.
- `run_chunks.sbatch` Array-job harness around the worker.

## Quickstart on Setonix (Pawsey)

Setonix runs Singularity (not Apptainer; same SIF format, same def
syntax, different command name) and does not permit on-system builds.
Build the Docker image in CI, push to a registry, pull on Setonix:

    module load singularity/<version>-nompi
    # keep the conversion cache off /home (small quota)
    export SINGULARITY_CACHEDIR=$MYSOFTWARE/.singularity
    singularity pull sedonadb.sif docker://ghcr.io/<you>/gdal-sedonadb:latest

The Pawsey nompi module auto-binds /scratch and /software. Images must
be Ubuntu 24.04+ after the CPE 25.03 upgrade (the gdal-r-python chain
already is). run_chunks.sbatch defaults to the singularity command;
set CONTAINER_EXEC=apptainer elsewhere.

## Quickstart (generic, own machine)

    apptainer build sedonadb.sif sedonadb.def

    # sanity: fixture round-trip inside the container
    apptainer exec sedonadb.sif python3 verify_zarr.py generate ./fixture.zarr
    apptainer exec sedonadb.sif python3 verify_zarr.py check ./fixture.zarr sst

    # then a real store
    apptainer exec sedonadb.sif python3 verify_zarr.py check \
        https://example.com/store.zarr variable_name

    # submit
    mkdir -p logs
    ZARR_URL="s3://bucket/store.zarr" ARRAY_NAME="sst" sbatch run_chunks.sbatch

    # resize shards / rerun failures without editing the script
    sbatch --array=0-63 run_chunks.sbatch
    sbatch --array=3,7,11 run_chunks.sbatch

## Package naming

The engine is the `sedonadb` wheel (`import sedonadb`;
`sedonadb.connect()`). The `apache-sedona` package is the umbrella
(Spark-era) distribution whose `sedona.db` module merely re-exports
`sedonadb`. Install `sedonadb sedonadb-zarr sedonadb-expr` directly; skip
the umbrella. The repo is apache/sedona-db; the wheel to cite in issues
is `sedonadb`.

`sd.register(sedonadb_zarr.ZarrExtension())` is mandatory before any
pixel-decoding operation (RS_Slice, RS_EnsureLoaded). Without it, decode
falls through to a 2-D-only GDAL loader and fails on N-D chunks; chunk
enumeration and envelope predicates work either way.

## What works (verified 0.4.0)

- Plain xarray-written stores, zarr v2 (consolidated) and v3.
- One row per storage chunk; RS_Envelope from coordinate arrays with
  pixel-edge extrapolation; chunk-level ST_Intersects pushdown.
- RS_Slice to a 2-D plane, and real decode through the zarrs codec
  chain (verified by corrupting chunks and observing decode failure).
- The reader is native Rust: zarrs + zarrs_object_store. No Python zarr
  in the read path.

## Constraints (verified or from source, 0.4.0)

- URL schemes: file://, s3://, http(s):// only. object_store is built
  without GCS, so gs:// stores need an https gateway.
- file:// URLs must be absolute (file:///abs/path); after file:// a URL
  expects a host, so file://./relative fails scheme parsing. Bare paths
  are fine; verify_zarr.py normalizes.
- Icechunk stores and kerchunk reference stores are not plain zarr
  layouts and do not read through the zarr extension (as of 0.4.0).
- Codecs via zarrs features: gzip, zlib, zstd, blosc, crc32c, sharding,
  transpose. No standalone LZ4 filter (blosc-lz4 is fine).
- CRS resolves from CF/rioxarray conventions; without a grid mapping or
  spatial_ref the SRID is 0 (envelopes still derive from coord arrays).
- Selection on non-spatial dims is positional only (integer indices);
  coordinate label arrays are deferred to a later phase upstream.

## Environment notes

- Never set a blanket LD_LIBRARY_PATH=/usr/local/lib in the image.
  It shadows the native libs bundled inside manylinux wheels (pyarrow's
  libarrow_substrait vs system abseil was the symptom). Register lib
  dirs via /etc/ld.so.conf.d + ldconfig instead: ldconfig paths resolve
  after a library's RUNPATH, LD_LIBRARY_PATH resolves before it.
- Multiple Arrow implementations in one process is normal and by
  design: GDAL's C++ Arrow, sedonadb's arrow-rs, pyarrow's bundled
  libarrow interoperate over the Arrow C Data Interface. Do not try to
  unify them outside a conda-style single-ABI build.
- sedonadb's pyarrow imports are lazy: count(), show(), to_parquet()
  run rust-side, so the slurm worker functions even where pyarrow is
  broken. verify_zarr.py degrades gracefully (skips dim introspection).
- pip in the image needs --break-system-packages on Ubuntu 24.04 unless
  installing into a venv.

## Acceptance test for image rebuilds

    python3 -c "from osgeo import gdal; import pyarrow, sedonadb; \
        print(gdal.__version__, pyarrow.__version__)"

GDAL first, pyarrow second: that ordering forces GDAL's /usr/local/lib
dependencies to load before the wheel's, which is the collision path.
