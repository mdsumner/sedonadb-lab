"""Ordered-import reproducer for the sedonadb configure_gdal("auto")
Arrow soname collision. Run inside any image with sedonadb installed:

    docker run --rm -v $PWD/repro.py:/repro.py IMAGE python3 /repro.py

Exit 0: not reproduced (no Arrow-linked libgdal for auto to find,
or wheel-mangled sonames). Exit nonzero: reproduced, either as the
soname takeover (latent) or the abseil ImportError (manifest).
"""

import subprocess, sys

CHECK = r'''
import sys
order = sys.argv[1]
if order == "pyarrow-first":
    import pyarrow; import sedonadb
else:
    import sedonadb
    try:
        import pyarrow
    except ImportError as e:
        print("MANIFEST: ImportError on pyarrow after sedonadb:")
        print("  " + str(e).splitlines()[0])
        sys.exit(2)
maps = open("/proc/self/maps").read().splitlines()
gdal = sorted(set(l.split(None, 5)[-1].strip() for l in maps if "libgdal" in l))
paths = sorted(set(l.split(None, 5)[-1].strip() for l in maps if "libarrow.so" in l))
wheel = any("/pyarrow/" in p for p in paths)
foreign = [p for p in paths if "/pyarrow/" not in p]
if order == "sedonadb-first":
    if gdal:
        print("eager mechanism: import sedonadb dlopened " + gdal[0])
        if not foreign:
            print("  (its Arrow is static/absent: no shared libarrow "
                  "soname registered -> this image is immune)")
    else:
        print("eager mechanism: no libgdal found by configure_gdal "
              "on this image -> nothing to load, immune by absence")
print(f"{order}: libarrow mapped from:")
for p in paths: print("   " + p)
if order == "sedonadb-first" and foreign and not wheel:
    print("TAKEOVER: pyarrow is running on a foreign libarrow "
          "(soname first-load-wins). Latent form of the bug.")
    sys.exit(1)
print("ok: pyarrow using its own bundled libarrow")
'''

rc = {}
for order in ("pyarrow-first", "sedonadb-first"):
    print("=" * 60)
    r = subprocess.run([sys.executable, "-c", CHECK, order])
    rc[order] = r.returncode

print("=" * 60)
if rc["pyarrow-first"] == 0 and rc["sedonadb-first"] != 0:
    print("REPRODUCED: behavior depends on import order.")
    print("Cause: configure_gdal('auto') at sedonadb import eagerly")
    print("dlopens libgdal, which loads the image's libarrow and")
    print("registers its soname before pyarrow can load its own.")
    sys.exit(1)
print("Not reproduced on this image/wheel combination.")
