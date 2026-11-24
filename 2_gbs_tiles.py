#!/usr/bin/env python3
r"""
Habitat tiles for the MSA parcel tool. Script 2 of 6. Double-click, or: python 2_gbs_tiles.py
Run once per Habitat Map version (about 1-3 h for all of Switzerland). Interrupted? Run again: it resumes.

What it does:
  1. Finds the Habitat Map of Switzerland (FOEN/WSL, ground cover layer) per canton in
     D:\NFA_data\1_sources\bafu\lebensraumkarte-schweiz\*\HabitatMap_*.gdb  (already on disk - nothing downloaded).
  2. Lists every TypoCH code in the map (one small table: codes.csv).
  3. Burns the TypoCH code into tiles: RES_M (2 m) pixels, 2 x 2 km per tile, LV95, pixel-centre rule.
     Cantons are merged at their borders. Empty tiles are not written.
  4. Counts the area of every code for all of Switzerland (national baseline on the web page).

Output: D:\NFA_data\4_projects\gbs_ch\tiles\<Habitat Map version>_<res>m\
          <E km>\<N km>.bin   one tile, zlib-compressed, north-up rows
          meta.json           codes, tile list, data version, file checksums of the source
          codes.csv           code index, TypoCH code, pixels, km2

Setup once: pip install geopandas rasterio   (the script installs rasterio itself if missing)
Next: 3_gbs_check.py (validation), 4_gbs_report.py, 5_gbs_web.py
"""
import json
import os
import subprocess
import sys
import time
import zlib
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gbs_core as core  # noqa: E402

BLOCK_M = 20000          # read the map in 20 x 20 km blocks (spatial index of the geodatabase)
# Speed (19 Nov 2026): the geodatabase stores rings in the ESRI order (outer clockwise, holes counter-clockwise).
# Without this, GDAL re-sorts the rings of every polygon with >100 holes (lakes, large forests) - very slow.
os.environ["OGR_ORGANIZE_POLYGONS"] = "ONLY_CCW"


def need(pkg, mod=None):
    try:
        return __import__(mod or pkg)
    except ImportError:
        print(f"Installing {pkg} (one time) ...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])
        return __import__(mod or pkg)


def find_layers(hab_dir):
    """[(canton, gdb path, layer name, bounds)] for the ground cover layer of every canton."""
    import pyogrio
    out = []
    for gdb in sorted(Path(hab_dir).glob("*/HabitatMap_*.gdb")):
        lay = [n for n, _ in pyogrio.list_layers(gdb) if n.startswith("HabitatMap_")]
        if not lay:
            continue
        info = pyogrio.read_info(gdb, layer=lay[0])
        out.append((gdb.stem.rsplit("_", 1)[-1], gdb, lay[0], tuple(info["total_bounds"])))
    return out


def main(hab_dir=None, out_root=None, res=core.RES_M, only=None):
    t_all = time.time()
    need("rasterio")
    import pyogrio

    hab_dir = Path(hab_dir or core.HABITAT_DIR)
    layers = find_layers(hab_dir)
    if only:
        layers = [l for l in layers if l[0].upper() in only]
    if not layers:
        sys.exit(f"No HabitatMap_*.gdb found in {hab_dir}\\*\\ - check the Habitat Map download.")
    version = "_".join(layers[0][2].split("_")[:4])                        # HabitatMap_v1_2_20251211
    out = Path(out_root or core.WORK / "tiles") / f"{version}_{res:g}m"
    out.mkdir(parents=True, exist_ok=True)
    T = core.TILE_M
    N = int(round(T / res))
    print(f"2_gbs_tiles.py - {core.VERSION}\nHabitat Map: {version}, {len(layers)} cantons\nTiles: {out}\n")

    # 1. codes
    print("Listing TypoCH codes ...")
    codes = set()
    for kt, gdb, lay, _ in layers:
        df = pyogrio.read_dataframe(gdb, layer=lay, columns=["TypoCH"], read_geometry=False)
        codes |= set(df["TypoCH"].astype(str).unique())
    # fixed order: by TypoCH level, then by the code as written ('1.1' and '1.1.x' must never swap)
    codes = ["nodata"] + sorted(codes, key=lambda c: ([int(x) if x.isdigit() else -1 for x in core.dotted(c).split(".")], c))

    state_f = out / "progress.json"
    state = json.loads(state_f.read_text()) if state_f.exists() else {}
    if state.get("codes") and set(state["codes"]) == set(codes):
        codes = state["codes"]                     # resumed run: keep the code numbers of the tiles on disk
    elif state.get("codes") or any(out.glob("*/*.bin")):
        old = out.with_name(out.name + "_old_" + time.strftime("%y%m%d%H%M"))
        out.rename(old)                            # other codes: never mix tiles; old ones kept aside
        out.mkdir(parents=True)
        print(f"  Habitat Map codes changed - earlier tiles moved to {old.name}, starting fresh")
        state = {}
    if not state.get("codes"):
        state = {"codes": codes, "done": [], "pixels": {}}
        state_f.write_text(json.dumps(state))      # fixes the code numbers before the first tile
    dtype = "uint8" if len(codes) <= 256 else "uint16"
    idx = {c: i for i, c in enumerate(codes)}
    print(f"  {len(codes) - 1} codes, stored as {dtype}")
    done = set(map(tuple, state["done"]))
    pix = {int(k): v for k, v in state["pixels"].items()}

    xmin = min(b[0] for *_, b in layers); ymin = min(b[1] for *_, b in layers)
    xmax = max(b[2] for *_, b in layers); ymax = max(b[3] for *_, b in layers)
    bx = range(int(xmin // BLOCK_M) * BLOCK_M, int(xmax) + 1, BLOCK_M)
    by = range(int(ymin // BLOCK_M) * BLOCK_M, int(ymax) + 1, BLOCK_M)
    blocks = [(x, y) for x in bx for y in by]
    verify(out, layers, done, idx, res, dtype, N)
    print(f"Burning {len(blocks)} blocks of {BLOCK_M // 1000} km ({len(done)} done before) ...")
    for i, (x0, y0) in enumerate(blocks, 1):
        if (x0, y0) in done:
            continue
        t = time.time()
        tiles = burn_block(layers, x0, y0, idx, res, dtype)
        # tiles touching a block edge may already exist from a neighbouring block: merge with the file
        n_new = 0
        for (te, tn), a in tiles.items():
            if not a.any():
                continue
            f = out / str(te // 1000) / f"{tn // 1000}.bin"
            f.parent.mkdir(exist_ok=True)
            if f.exists():
                old = np.frombuffer(zlib.decompress(f.read_bytes()), dtype=dtype).reshape(N, N)
                a = np.where(old == 0, a, old)
            f.write_bytes(zlib.compress(a.tobytes(), 9))
            n_new += 1
        done.add((x0, y0))
        state["done"] = sorted(done)
        state_f.write_text(json.dumps(state))
        print(f"  block {i}/{len(blocks)}  E {x0 // 1000} N {y0 // 1000}: {n_new} tiles, {time.time() - t:.0f} s")

    # 2. national counts plus meta (from the finished tiles, so a resumed run counts every tile once)
    print("Counting pixels per code ...")
    pix = np.zeros(len(codes), dtype=np.int64)
    tile_list, size = [], 0
    for f in sorted(out.glob("*/*.bin")):
        a = np.frombuffer(zlib.decompress(f.read_bytes()), dtype=dtype)
        pix += np.bincount(a, minlength=len(codes))
        tile_list.append([int(f.parent.name), int(f.stem)])
        size += f.stat().st_size
    with open(out / "codes.csv", "w", encoding="utf-8", newline="") as fh:
        fh.write("index,typoch_map,typoch,pixels,km2\n")
        for i, c in enumerate(codes):
            fh.write(f"{i},{c},{core.dotted(c) if i else ''},{pix[i]},{pix[i] * res * res / 1e6:.4f}\n")
    sources = []
    for kt, gdb, lay, b in layers:
        big = max(gdb.glob("*.gdbtable"), key=lambda p: p.stat().st_size)
        sources.append({"canton": kt, "gdb": gdb.name, "layer": lay, "bytes": big.stat().st_size,
                        "modified": time.strftime("%Y-%m-%d", time.localtime(big.stat().st_mtime))})
    meta = {"dataset": version, "res": res, "tile_m": T, "dtype": dtype, "crs": "EPSG:2056",
            "codes": codes, "pixels": pix.tolist(), "tiles": tile_list, "bytes": size,
            "made": time.strftime("%Y-%m-%d %H:%M"), "tool": core.VERSION, "sources": sources,
            "rule": "pixel centre inside polygon (rasterio.features.rasterize, all_touched=False); "
                    "first canton wins on shared pixels"}
    (out / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    print(f"\nDone: {len(tile_list)} tiles, {size / 1e6:,.0f} MB, {pix[1:].sum() * res * res / 1e6:,.0f} km2 mapped "
          f"in {(time.time() - t_all) / 60:.0f} min.")
    if size > 900e6:
        print("WARNING: over 900 MB - GitHub Pages allows 1 GB per site. Set RES_M to 2.5 in gbs_core.py.")


def burn_block(layers, x0, y0, idx, res, dtype):
    """Burns one 20 x 20 km block in one go per canton, then cuts it into 2 x 2 km tiles.
    Same grid, same pixel-centre rule as tile by tile - only faster: each polygon is drawn once."""
    import pyogrio
    import rasterio.features as rf
    from affine import Affine
    T = core.TILE_M
    N = int(round(T / res))
    NB = int(round(BLOCK_M / res))
    block = None
    for kt, gdb, lay, b in layers:
        if b[0] > x0 + BLOCK_M or b[2] < x0 or b[1] > y0 + BLOCK_M or b[3] < y0:
            continue
        df = pyogrio.read_dataframe(gdb, layer=lay, columns=["TypoCH"], bbox=(x0, y0, x0 + BLOCK_M, y0 + BLOCK_M))
        if df.empty:
            continue
        a = rf.rasterize(zip(df.geometry, df["TypoCH"].astype(str).map(idx)), out_shape=(NB, NB), fill=0,
                         dtype=dtype, transform=Affine(res, 0, x0, 0, -res, y0 + BLOCK_M))
        block = a if block is None else np.where(block == 0, a, block)   # first canton wins on a shared pixel
        del df, a
    tiles = {}
    if block is None:
        return tiles
    k = BLOCK_M // T
    for ci in range(k):
        for ri in range(k):
            tiles[(x0 + ci * T, y0 + BLOCK_M - (ri + 1) * T)] = np.ascontiguousarray(
                block[ri * N:(ri + 1) * N, ci * N:(ci + 1) * N])
    return tiles


def verify(out, layers, done, idx, res, dtype, N):
    """Resumed run: burns one finished block again with this version and compares it with the tiles
    already on disk. Allowed: pixels whose centre lies exactly on a polygon edge (the Habitat Map has
    its edges on the 1 m grid, our 2 m pixel centres too) - there either side is correct, rounding decides.
    Anything else, or more than 1 in 10'000 pixels, stops the script before it writes a tile."""
    files = {}
    for (x0, y0) in sorted(done):
        fs = [f for f in out.glob("*/*.bin")
              if x0 <= int(f.parent.name) * 1000 < x0 + BLOCK_M and y0 <= int(f.stem) * 1000 < y0 + BLOCK_M]
        if fs:
            files[(x0, y0)] = fs
    if not files:
        return
    (x0, y0), fs = max(files.items(), key=lambda kv: len(kv[1]))      # the largest finished block: the hardest test
    print(f"Check: burning block E {x0 // 1000} N {y0 // 1000} again ({len(fs)} tiles) and comparing ...")
    t = time.time()
    new = burn_block(layers, x0, y0, idx, res, dtype)
    total, diffs = 0, []
    for f in fs:
        old = np.frombuffer(zlib.decompress(f.read_bytes()), dtype=dtype).reshape(N, N)
        te, tn = int(f.parent.name) * 1000, int(f.stem) * 1000
        a = new.get((te, tn))
        total += old.size
        if a is None:
            a = np.zeros_like(old)
        for r, c in zip(*np.nonzero(old != a)):
            diffs.append((te + (c + 0.5) * res, tn + core.TILE_M - (r + 0.5) * res))
    edge = other = 0
    if diffs:
        import pyogrio
        import shapely
        pts = shapely.points(np.array(diffs))
        on_edge = np.zeros(len(diffs), bool)
        for kt, gdb, lay, b in layers:
            if b[0] > x0 + BLOCK_M or b[2] < x0 or b[1] > y0 + BLOCK_M or b[3] < y0:
                continue
            df = pyogrio.read_dataframe(gdb, layer=lay, columns=["TypoCH"], bbox=(x0, y0, x0 + BLOCK_M, y0 + BLOCK_M))
            hit_p, hit_g = df.sindex.query(pts, predicate="intersects")
            d = shapely.distance(pts[hit_p], shapely.boundary(df.geometry.values[hit_g]))
            on_edge[hit_p[d < 1e-6]] = True                       # pixel centre exactly on a polygon edge
        edge = int(on_edge.sum())
        other = len(diffs) - edge
    if other or edge > total / 10000:
        sys.exit(f"STOP: {other:,} pixels differ inside habitats, {edge:,} on edges, of {total:,}. "
                 "Nothing written. Send Claude a screenshot.")
    print(f"  same tiles: {total - edge:,} of {total:,} pixels identical, {edge} edge pixels decided the other way "
          f"(centre exactly on a polygon edge) - {time.time() - t:.0f} s\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped. Run again to resume.")
    except SystemExit as e:
        if e.code not in (None, 0):
            print(e.code)
    except Exception:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("\nSomething went wrong - send Claude a screenshot of this window.")
    finally:
        if sys.stdin and sys.stdin.isatty() and __name__ == "__main__":
            input("\nPress Enter to close.")
