# SedonaDB and GDAL multidim: a development plan

Dev draft. 2026-10-20. Anchored to apache/sedona-db at PR #1449 (merged,
closes #1395) and design issue #746.

## Where things stand

sedona-db's N-dimensional path is a native Zarr reader: the
`sedona-raster-zarr` crate on `zarrs` and `object_store` (file, s3, http),
one table row per storage chunk, envelopes derived from coordinate arrays,
pixels decoded on demand. GDAL appears only through the classic 2-D API: a
MEM-dataset path (a pinned `MEMDataset::Create` symbol as of #1449) used as
the compute escape hatch once a plane has been sliced out of the cube. The
multidim API (`GDALGroup`, `GDALMDArray`) appears nowhere, so every format
multidim reaches - NetCDF, HDF4/5, GRIB, multidim VRT, /vsi composition -
is invisible to the cube path, and reference stores (kerchunk-parquet,
Icechunk manifests) do not read either.

#1449 also moved GDAL/PROJ runtime discovery into a shared Rust module
(`native_library.rs`) used by all bindings, added `sd_configure_gdal()` to
the R package with load-time auto-configuration, and made the system preset
find versioned runtime libraries (`libgdal.so.NN`) without a dev symlink.
The Zarr extension itself remains a Python-only wheel.

## The thesis

One chunk relation sits under all of this. Live Zarr metadata, multidim
chunk enumeration (OSGeo/gdal#14677), kerchunk-parquet, Icechunk manifests
and ad hoc byte-reference harvests are serializations of the same relation:
array identity, integer chunk indices, byte location, codec recipe,
georeferencing. sedona-db currently derives that relation from exactly one
source - live Zarr metadata, at query time. Two schema additions make the
relation an input rather than a derivation, at which point GDAL multidim
becomes the universal feeder and virtual datasets become first-class:
byte-range references, and chunk indices as columns.

## Planned items

| # | target | kind | one line | status |
|---|---|---|---|---|
| P1 | apache/sedona-db | issue + small PR | defer runtime configuration from package import to first use | [drafts/issue-defer-config.md](drafts/issue-defer-config.md), refreshed post-#1449 |
| P2 | apache/sedona-db | design issue, then PR | byte-range outdb references and chunk-index columns | scoped; evidence ready |
| P3 | apache/sedona-db #746 | comments | dims-as-struct, coordinate descriptors, read/regrid contract | time-sensitive: before Phase 1 ossifies the schema |
| P4 | OSGeo/gdal #14677 | PR (in flight) | multidim chunk byte-reference enumeration | under review upstream |
| P5 | apache/sedona-db | issue | R surface for the Zarr extension | opportunistic |

### P1. Defer runtime configuration to first use

The Python package runs `configure_proj("auto")` and
`configure_gdal("auto")` at import. The auto preset probes rasterio,
pyogrio, conda, homebrew and system in order and eagerly dlopens the first
libgdal found. Where that libgdal is dynamically linked against a shared,
unmangled Arrow C++ (the common institutional recipe: distro
`libarrow-dev` plus GDAL built with the Parquet driver), the system
libarrow soname registers in the process before pyarrow can load its own
copy; a later `import pyarrow` reuses it (soname first-load-wins) and
fails with an undefined abseil symbol, even at identical Arrow versions.
Clearing `LD_LIBRARY_PATH` does not help; import order does.

Evidence in hand: a two-line ordered-import reproducer; process-map
attribution; and a four-environment matrix run with one test file - the
project's published image (contains no GDAL: immune by absence, and warns
on every import), pip wheel installs (mangled sonames, plus pyogrio
importing pyarrow as a side effect: doubly immune), the osgeo/gdal
ubuntu-full image (eager load fires, Arrow statically linked: immune), and
a source-built GDAL against shared libarrow (collision). The project's own
docstrings state configuration has no effect after the first GDAL-backed
operation, so deferring it there is semantics-preserving. Post-#1449 the
discovery logic is centralized in `native_library.rs`, which is the
natural landing zone; the import-time calls themselves are unchanged.

### P2. Byte-range references and chunk-index columns

The band struct's `outdb_uri` names a whole storage object, with chunk
identity buried in a URI fragment. Two additions: a byte-range reference
(`uri`, `offset`, `length`, `codec_chain`), and integer chunk indices as
relational columns. That unlocks, in one mechanism: Zarr v3 shards
addressed directly; kerchunk-parquet and Icechunk manifests read as the
chunk table (archives queryable without a Zarr rewrite; snapshots as time
travel; no metadata round-trips at plan time); and the output of multidim
enumeration (P4) fed straight in. Codec belongs in the schema, not the
loader: a missing codec column is silent garbage. Motivating dataset: a
REMA v2 reference store of roughly 19.5 million chunk references.

### P3. Schema comments on #746

Three points, best made while the Arrow encoding is still an issue rather
than a codebase. First, `dim_names` / `shape` / `strides` as parallel
lists leave nowhere to hang per-dimension metadata; a list of dim structs
(name, size, coordinate descriptor) gives the deferred "coordinate label
arrays" phase a home. Second, a coordinate descriptor union -
affine(offset, step), explicit reference, none - subsumes the raster-level
y/x transform as a special case, covers irregular 1-D spacing, and the
explicit-reference case is the only representation that works for
curvilinear 2-D coordinates (ocean and model grids, where no affine
exists). Third, the read contract for the GDAL-backed execution path:
shape is an output, not an input, and anything that changes the grid is a
named regrid operation - determinism matters more in a database than
anywhere.

### P4. Multidim enumeration upstream

OSGeo/gdal#14677 adds a multidim chunk byte-reference subcommand: the
chunk relation, emitted by GDAL, for every format multidim reaches. With
P2 in place the mapping from enumerator output onto band structs is nearly
mechanical for regular grids, and sedona-db gains the long tail of formats
without writing per-format readers.

### P5. R surface for the Zarr extension

With #1449, GDAL-backed raster functions work from a stock R install. The
N-dimensional path is still Python-only (the Zarr extension ships as a
wheel). The ask: an R binding surface for the Zarr reader and the
dimension functions, so the R-first datacube path reaches the cube, not
just the plane.

## Sequencing

P3 first (schema windows close); P1 next (it is small, self-contained and
already evidenced); P4 continues on its own track; P2 is the substantive
design conversation and lands strongest with P1 filed and P4 visible; P5
whenever convenient. Working assets - the container and slurm kit, a
generate-and-verify fixture script (enumerate / slice / decode against any
store), and the ordered-import reproducer with per-image mechanism
reporting - live in this repository alongside the issue drafts.
