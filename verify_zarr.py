"""Verify a Zarr store works with sedonadb-zarr, or generate a known-good one.

Usage:
    python verify_zarr.py generate ./fixture.zarr        # local known-good cube
    python verify_zarr.py check <url> <array_name>       # test any store

check runs three stages of increasing depth:
  1. enumerate  - one row per chunk, metadata only (proves store + layout)
  2. slice      - RS_Slice a 2-D plane (proves N-D dims resolved)
  3. decode     - RS_EnsureLoaded on one chunk (proves codec support;
                  codec config is per-array so one chunk suffices --
                  this is a compatibility check, not an integrity scan)

Verified against sedonadb 0.4.x: plain xarray-written stores work, zarr
v2 (consolidated) and v3, default codecs. Known constraints:
  - object_store built with aws/fs/http only: file://, s3://, https://
    work; gs:// does NOT (WeatherBench, ARCO-ERA5 on GCS are out unless
    they have an https gateway).
  - Icechunk stores and kerchunk reference stores are NOT plain zarr and
    will not read through this extension.
  - Codecs via zarrs: gzip, zlib, zstd, blosc, crc32c, sharding,
    transpose. No standalone LZ4 filter.
  - CRS resolves from CF/rioxarray conventions; without a spatial_ref or
    grid_mapping the SRID is 0 (envelopes still derived from coord arrays).
"""

import os
import sys

import sedonadb
import sedonadb_zarr


def normalize_url(url):
    """Bare paths and file://relative both become file:///abs/path.

    In a URL the segment after file:// is a *host*, so file://./x parses
    as host "." and object_store rejects the scheme. Only absolute
    file:/// or bare paths work; normalize everything to the former.
    """
    if "://" not in url:
        return "file://" + os.path.abspath(url)
    if url.startswith("file://") and not url.startswith("file:///"):
        return "file://" + os.path.abspath(url[len("file://"):])
    return url


def have_pyarrow():
    try:
        import pyarrow  # noqa: F401
        return True
    except Exception as e:
        print("WARNING: pyarrow is broken in this environment:")
        print("  " + str(e).splitlines()[0])
        print("  (often an LD_LIBRARY_PATH clash with a system Arrow/abseil;")
        print("   try: LD_LIBRARY_PATH= python -c 'import pyarrow')")
        print("  Running degraded checks: enumerate + decode, skipping dim")
        print("  introspection. sedonadb itself is unaffected (rust-side).")
        return False


def generate(path):
    import numpy as np
    import xarray as xr

    time = np.arange(4)
    y = np.linspace(-40.0, -60.0, 64)
    x = np.linspace(100.0, 160.0, 128)
    ds = xr.Dataset(
        {"sst": (("time", "y", "x"),
                 np.random.rand(4, 64, 128).astype("float32"))},
        coords={"time": time, "y": y, "x": x},
    )
    ds.attrs["Conventions"] = "CF-1.7"
    ds.to_zarr(path, zarr_format=2, consolidated=True,
               encoding={"sst": {"chunks": (1, 32, 64)}})
    import os
    print(f"wrote {path}; now run: python verify_zarr.py check "
          f"{os.path.abspath(path)} sst")


def check(url, array_name):
    url = normalize_url(url)
    pa_ok = have_pyarrow()

    sd = sedonadb.connect()
    sd.register(sedonadb_zarr.ZarrExtension())

    spec = sedonadb_zarr.Zarr().with_options({"arrays": [array_name]})
    cube = sd.read(url, format=spec)
    cube.to_view("cube", overwrite=True)

    n = cube.count()
    print(f"[1/3] enumerate: OK, {n} chunk rows")

    meta_sql = (
        "SELECT RS_NumDimensions(raster) ndim, RS_DimNames(raster) dims, "
        "RS_Shape(raster) shape, RS_SRID(raster) srid FROM cube LIMIT 1"
    )
    if pa_ok:
        meta = sd.sql(meta_sql).to_arrow_table().to_pylist()[0]
        dims = [str(d) for d in meta["dims"]]
        print(f"[1/3] dims={dims} shape={meta['shape']} srid={meta['srid']}" +
              ("  (srid 0: no CF/rioxarray CRS found)"
               if meta["srid"] == 0 else ""))
        ndim = int(meta["ndim"])
        if ndim > 2:
            # slice away leading dims to reach a 2-D plane
            expr = "raster"
            for d in dims[:-2]:
                expr = f"RS_Slice({expr}, '{d}', 0)"
            shape2d = sd.sql(
                f"SELECT RS_Shape({expr}) s FROM cube LIMIT 1"
            ).to_arrow_table().to_pylist()[0]["s"]
            print(f"[2/3] slice: OK, plane shape {shape2d}")
        else:
            print("[2/3] slice: skipped (already 2-D)")
    else:
        sd.sql(meta_sql).show()
        print("[2/3] slice: skipped (pyarrow unavailable for dim parsing)")

    sd.sql(
        "SELECT RS_Metadata(RS_EnsureLoaded(raster)) m FROM cube LIMIT 1"
    ).show(limit=1)  # rust-side; printing the row forces one real chunk decode
    print("[3/3] decode: OK (one chunk loaded through zarr codec chain)")
    print(f"PASS: {url} [{array_name}]")


if __name__ == "__main__":
    if sys.argv[1] == "generate":
        generate(sys.argv[2])
    elif sys.argv[1] == "check":
        check(sys.argv[2], sys.argv[3])
    else:
        sys.exit(__doc__)
