"""One SedonaDB engine per slurm array task, sharded by chunk rows.

sedonadb-zarr emits one row per Zarr chunk, so sharding is just row
partitioning. Here we shard on the chunk envelope against a regular
grid of spatial windows; swap the predicate for a time/dim filter if
that suits the dataset better (e.g. slice ranges on a 'time' dim).

Usage: python worker.py <task_id> <n_tasks> <zarr_url> <array_name> <outdir>
"""

import sys

import sedonadb
import sedonadb_zarr
from sedonadb import functions as f


def window_wkt(task_id, n_tasks, xmin=-180.0, xmax=180.0, ymin=-90.0, ymax=90.0):
    """Split the x-range into n_tasks vertical strips (lon/lat, EPSG:4326)."""
    w = (xmax - xmin) / n_tasks
    x0 = xmin + task_id * w
    x1 = x0 + w
    return (
        f"POLYGON(({x0} {ymin}, {x1} {ymin}, {x1} {ymax}, "
        f"{x0} {ymax}, {x0} {ymin}))"
    )


def main(task_id, n_tasks, url, array_name, outdir):
    sd = sedonadb.connect()

    # Required for any pixel-decoding op (RS_Slice, RS_EnsureLoaded, ...).
    # Without this, decode falls back to a 2-D-only GDAL loader and fails
    # on N-D chunks. Chunk enumeration/envelopes work either way.
    sd.register(sedonadb_zarr.ZarrExtension())

    spec = sedonadb_zarr.Zarr().with_options({"arrays": [array_name]})
    cube = sd.read(url, format=spec)

    # Filter chunk rows by footprint: metadata-only until pixels are pulled.
    wkt = window_wkt(task_id, n_tasks)
    mine = cube.filter(
        f.st_intersects(
            f.st_transform(cube.raster.rst.envelope(), "EPSG:4326"),
            f.st_geomfromtext(wkt),
        )
    )

    # Example reduction: per-chunk footprint + summary. Replace with the
    # real computation (RS_Slice, band math, zonal stats, ...).
    result = mine.select(
        f.st_transform(mine.raster.rst.envelope(), "EPSG:4326").alias("geom"),
        mine.raster.rst.shape().alias("shape"),
        mine.raster.rst.dim_names().alias("dims"),
    )

    out = f"{outdir}/part-{task_id:04d}.parquet"
    result.to_parquet(out)
    print(f"task {task_id}/{n_tasks}: wrote {out}")


if __name__ == "__main__":
    tid, ntasks = int(sys.argv[1]), int(sys.argv[2])
    main(tid, ntasks, sys.argv[3], sys.argv[4], sys.argv[5])
