# Notes toward upstream conversation (apache/sedona-db)

Working notes, July 2026. Context: sedona-db 0.4.0, N-D raster design in
issue #746, Phase 1 in progress. No GitHub Discussions on the repo;
venues are issues, dev@sedona.apache.org, Discord. paleolimbot currently
the most active committer on main.

## Layer map

Four projects, one object, four granularities:

- gdalxarray: array veneer; GDAL as IO source of truth rendering into
  labelled arrays. Not relational.
- xrdbi: pixel-level relation; tables are variables, statements are
  selection graphs, fetch renders long-form rows.
- sedona-db zarr: chunk-level relation; one row per storage chunk,
  envelopes from metadata, blobs decoded on demand.
- blocklist / dbi-for-xarray design: byte-reference relation;
  (array_id, i, j, ..., location, offset, length, etag) persisted as
  parquet.

The dbi-for-xarray normal form (chunk relation + codec recipe + six
numbers) and the #746 Arrow schema (crs + transform[6] + bands with
dim_names/shape/outdb_uri) are the same design reached independently.

## Their band struct (from #746)

    Struct {
      crs:        Utf8View,
      transform:  List<Float64>,      # 6-number affine, y/x only
      bands: List<Struct {
        name, dim_names: List, shape: List, data_type: UInt32,
        nodata: Binary, strides: List, offset: UInt64,
        outdb_uri: Utf8,              # "zarr://s3://b/store#var/0.0.0"
        data: BinaryView,             # bytes (eager) or empty (lazy)
      }>
    }

Lazy/eager = empty data + outdb_uri vs bytes present; RS_EnsureLoaded
flips it. strides/offset make slices zero-copy views (Arrow BinaryView
refcounts the buffer). Two-method trait underneath: nd_buffer() for
zero-copy, contiguous_data() -> Cow. Phase 2 adds LazySlicedBand so
RS_DimToBand stays lazy. Phase 3 lists coordinate label arrays and
dimension algebra (i.e. coordinates acknowledged, deferred).

Character of the design: N-D storage, 2-D georeferencing, 2-D compute
escape hatch (RS_DimToBand + GDAL exec path). GDAL-classic in spirit,
not xarray/mdim (dimensions-with-coordinates) in spirit.

## Generalization to mdim chunks

The band atom essentially is an mdim chunk descriptor; mapping GDAL
mdim chunk enumeration (gdal mdim list-chunks) into band structs is
nearly mechanical for regular grids. Three seams:

1. Chunk identity lives in the URI fragment (#var/0.0.0), not integer
   columns. Relational pushdown and joins want (i, j, k) as columns.
2. No remote byte ranges: the offset field is a view offset into the
   local buffer, not into a remote object. Rules out direct zarr v3
   shard addressing, kerchunk references, blocklist rows. The missing
   fields are (uri, offset, length, codec_chain).
3. Coordinate model does not generalize: six numbers for y/x, every
   other dim is name + size. Positional-only selection, no irregular
   spacing, no time labels, no curvilinear 2-D coords. Parallel lists
   (dim_names/shape/strides) leave nowhere to hang a per-dim coordinate
   descriptor when Phase 3 arrives. A dims: List<Struct{name, size,
   coord: union{affine(offset, step) | explicit ref | none}}> subsumes
   the y/x affine and covers irregular 1-D; curvilinear needs a 2-D
   coord ref via the same union.

## Asks, ranked

0. Bug with reproducer: importing sedonadb eagerly imports rasterio
   and pyogrio at package-import time, loading libgdal and (where GDAL
   links Arrow) the system libarrow, which poisons the libarrow soname
   for a later pyarrow import (undefined abseil symbol in the wheel's
   substrait; both Arrows 25.0.0, different vendored abseil LTS).
   Reproducer: "import pyarrow; import sedonadb" works,
   "import sedonadb; import pyarrow" fails; /proc/self/maps shows the
   system libarrow mapped by the sedonadb import alone. Proposed fix:
   lazy-import rasterio/pyogrio in the Python GDAL loader on first
   use. Also improves import time and removes a hard dependency for
   users who never touch the GDAL loader.
1. Reference-store input: accept a persisted chunk relation
   (kerchunk-parquet, Icechunk manifest, blocklist output) as the chunk
   table, via a byte-range outdb scheme. One mechanism unlocks the
   virtual world: archives never rewritten to zarr, Icechunk snapshots
   as time travel, zero metadata round-trips at plan time. Motivating
   dataset: REMA v2 reference store, 19.5M chunks.
2. Comment on #746 before Phase 1 freezes the schema: dims-as-struct
   (so Phase 3 coordinates have a home) and byte-range outdb fields.
   Curvilinear grids (ROMS, CICE, BRAN2023) as the concrete case for
   why a single raster-level affine cannot be the only georeferencing.
3. Read contract: shape is an output, not an input; grid changes are
   regrid(), a named operation. Matters more in a database (answers
   should be deterministic and assertable). Relevant to their
   GDAL-backed execution path design.
4. GDAL mdim as long-tail ingest: GDAL enumerates chunks (list-chunks
   upstream work), sedona-db tables them. Closes the format gap
   (GRIB, HDF4/5, multidim VRT, /vsi composition) without new readers.
5. Codec chain into the band schema, not the loader. A missing codec
   column (e.g. predictor) is silent garbage; the schema must own it.
   Required the moment outdb generalizes past zarr-native.

## Take, not just give

- DataFusion/sedona-db as an arrplyr backend: the chunk relation inside
  a real optimizer makes chunk-grid x polygon-table spatial joins a
  single planned query (e.g. which REMA chunks intersect 10k RGI
  polygons) rather than client-side loops.
- Align the blocklist parquet schema with their Arrow raster encoding:
  if the columns match, the integration is a file format, not
  software coupling.
- One-row-per-chunk as user-facing API is validated: people will query
  the chunk grid directly (draw it on a map from metadata alone). A
  blocklist -> duckdb/sedona view demo is cheap and communicates the
  whole manifest-first architecture.

## Suggested sequence

Short direct note first (three paragraphs: convergent normal form; what
each side is missing; offer of datasets and enumeration tooling). Then
the durable artifacts: one issue proposing reference-store input via
the outdb scheme mechanism, one comment on #746 re dims-as-struct and
curvilinear coordinates. ASF projects run on the record; the issue is
what survives. The 0.4 release explicitly solicited datacube feedback.
