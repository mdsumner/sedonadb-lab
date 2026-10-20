# sedonadb-lab

Experiments, working kits and upstream drafts around
[apache/sedona-db](https://github.com/apache/sedona-db) - the embedded,
single-node spatial engine (DataFusion + Arrow) and its N-dimensional
raster/Zarr direction.

One subtree per experiment; each carries its own plan, drafts and
working assets. Issue and PR drafts are plain markdown, ready to file
verbatim; once filed, the parked draft is replaced with a link to the
live issue so GitHub holds the canonical text.

## Experiments

| subtree | status | one line |
|---|---|---|
| [mdim/](mdim/) | active | SedonaDB and GDAL multidim via the chunk relation: the development plan ([mdim/plan.md](mdim/plan.md)), upstream issue drafts, and the Setonix/slurm verification kit |

## Context

Upstream anchors so far: apache/sedona-db issue #1395 (R GDAL
configuration; closed by PR #1449), design issue #746 (N-D raster
model), and OSGeo/gdal#14677 (multidim chunk byte-reference
enumeration). Indexed from
[hypertidy.org/writing](https://www.hypertidy.org/writing).
