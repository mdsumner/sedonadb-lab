# Draft issue for apache/sedona-db

Title:

    Eager configure_gdal("auto") at package import registers a system
    libarrow soname, breaking a later "import pyarrow" (undefined
    abseil symbol); proposal: defer configuration to first use

Body below the line. Fill in the two TODO placeholders before posting.

---

## Summary

`sedonadb/__init__.py` calls `configure_gdal("auto")` and
`configure_proj("auto")` at package import. The "auto" preset probes
(rasterio, pyogrio, conda, homebrew, system) and eagerly dlopens the
first libgdal it finds. In environments where that libgdal links a
system Arrow C++ with unmangled sonames (for example GDAL built with
the Parquet driver against distro `libarrow-dev`), the system
`libarrow.so.<N>` soname is registered in the process at
`import sedonadb`. A later `import pyarrow` then reuses the
already-loaded system copy instead of the wheel's own `$ORIGIN` copy
(soname first-load-wins), and pyarrow's `libarrow_substrait` fails
with an undefined abseil symbol, because the distro Arrow vendors a
different abseil LTS than the manylinux wheel -- even at identical
Arrow versions.

## Reproducer

Environment: sedonadb 0.4.0, pyarrow 25.0.0 (manylinux wheel),
Python 3.12, Ubuntu 24.04 container; GDAL 3.14.0 built from source
with the Parquet/Arrow driver against apt `libarrow-dev`
(Arrow 25.0.0); rasterio and pyogrio built from source against that
GDAL. Observed on HPC via Singularity but nothing here is
container-specific.

```
$ python3 -c "import pyarrow; import sedonadb; print('ok')"
ok

$ python3 -c "import sedonadb; import pyarrow; print('ok')"
ImportError: .../pyarrow/libarrow_substrait.so.2500: undefined symbol:
_ZN4absl12lts_2026010719str_format_internal13FormatArgImpl8DispatchIlEEb...
```

Both Arrows are 25.0.0; the missing symbol is from abseil
lts_20260107 (wheel expectation), while the distro Arrow statically
vendors an older LTS.

Confirmation that the sedonadb import alone maps the system Arrow:

```
$ python3 -c "import sedonadb; print(*[l for l in open('/proc/self/maps')
    if 'arrow' in l or 'gdal' in l], sep='')"
...
/usr/lib/x86_64-linux-gnu/libarrow.so.2500.0.0
/usr/lib/x86_64-linux-gnu/libarrow_acero.so.2500.0.0
/usr/lib/x86_64-linux-gnu/libarrow_compute.so.2500.0.0
/usr/lib/x86_64-linux-gnu/libarrow_dataset.so.2500.0.0
/usr/local/lib/libgdal.so.39.3.14.0
```

The chain: `import sedonadb` -> `configure_gdal("auto")` -> rasterio
preset -> rasterio's extension loads libgdal -> libgdal loads system
libarrow. The eager dlopen is not specific to the rasterio preset:
`configure_gdal("system", ...)` attempts the dlopen immediately as
well, and on a source-built stack the pyogrio preset reaches the same
Arrow-linked libgdal. So this is not "rasterio's fault"; any preset
that finds an Arrow-linked libgdal has the same effect.

## Why CI does not see this

On stock wheel installs the cascade is accidentally protected twice:

1. pyogrio imports pyarrow as a side effect, so the probe itself
   loads pyarrow's Arrow first and it wins the soname race (visible
   as `"pyarrow" in sys.modules` after a bare `import sedonadb`).
2. Wheel-bundled GDALs carry auditwheel-mangled sonames
   (e.g. `libgdal-253d08a6.so.38`) whose Arrow deps, if any, are also
   mangled and cannot collide with pyarrow's.

Source-built geospatial stacks (custom Docker images, HPC, anywhere
GDAL is compiled against distro Arrow) remove both protections at
once.

## Proposed fix

Defer `configure_gdal` / `configure_proj` from package import to
immediately before the first GDAL-backed operation / first transform.
The docstrings already state that configuration has no effect once
the first such operation has been performed, so the only moment
configuration can matter is directly before it -- lazy configuration
is semantics-preserving. Side benefits: no soft-dependency probe or
GDAL/PROJ load cost at import for users who never touch the GDAL
loader (e.g. Zarr-only workloads), and faster `import sedonadb`.

A smaller mitigation (not sufficient on its own, but cheap) would be
an environment variable to skip auto-configuration at import.

## Workarounds we are using

- Import pyarrow before sedonadb (or a guarded `import pyarrow` in
  `sitecustomize.py`), which pins the wheel's Arrow as the soname
  winner.
- Note that clearing `LD_LIBRARY_PATH` does NOT fix the
  sedonadb-first ordering: soname reuse of an already-loaded library
  ignores search paths.

Happy to test a patch; the environment above is reproducible on
demand. (Context: hit while evaluating the sedonadb-zarr extension
for N-D datacube work on HPC -- TODO optional: link to your repo.)

TODO: fill in `sedonadb.__version__` / exact wheel tags if you want
them pinned more precisely than 0.4.0.
