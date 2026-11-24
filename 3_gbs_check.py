#!/usr/bin/env python3
r"""
Validation: tile method versus exact polygon overlay. Script 3 of 6. Double-click, or: python 3_gbs_check.py

Question: how far is the MSA from the 2 m tiles (what the web page and the reports use) from an exact
intersection of the parcel with the Habitat Map polygons (no pixels at all)?

Test set (fixed random seed, so every run checks the same parcels):
  - every polygon in 01_Input
  - 40 squares of 1 ha, 40 squares of 10 ha, 40 strips 15 m x 400 m (embankment-like), at random places
    inside the cantons of the Habitat Map
Exact overlay: shapely intersection with the original Habitat Map polygons (geodatabase), areas in LV95.

Output: 03_Validation\validation_<yymmdd>.csv  one row per test parcel: MSA tile, MSA exact, difference
        03_Validation\validation_summary.json   mean and largest difference - shown on the web page
"""
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gbs_core as core  # noqa: E402

N_EACH = 40
SEED = 20261119


def tiles_dir():
    found = sorted((core.WORK / "tiles").glob("*/meta.json"))
    if not found:
        sys.exit("No tiles found - run 2_gbs_tiles.py first.")
    return found[-1].parent


def exact(poly, layers, ref, coef):
    """Exact overlay: area-weighted MSA (central and conservative) of the original polygons."""
    import pyogrio
    from shapely.geometry import Polygon
    shp = Polygon(poly[0][0], poly[0][1:]) if len(poly) == 1 else None
    if shp is None:
        from shapely.geometry import MultiPolygon
        shp = MultiPolygon([(p[0], p[1:]) for p in poly])
    b = shp.bounds
    num = {"central": 0.0, "conservative": 0.0}
    area = 0.0
    for kt, gdb, lay, bb in layers:
        if bb[0] > b[2] or bb[2] < b[0] or bb[1] > b[3] or bb[3] < b[1]:
            continue
        df = pyogrio.read_dataframe(gdb, layer=lay, columns=["TypoCH"], bbox=b)
        if df.empty:
            continue
        inter = df.geometry.intersection(shp)
        for code, a in zip(df["TypoCH"], inter.area):
            if a <= 0:
                continue
            row = core.match_row(code, ref["mapping"])
            if not row["terr"]:
                continue
            area += a
            num["central"] += a * coef[row["c"]]["msa"]
            num["conservative"] += a * coef[row["k"]]["msa"]
    return {k: v / area if area else None for k, v in num.items()}, area


def main(hab_dir=None, tdir=None, out_dir=None):
    import importlib.util
    spec = importlib.util.spec_from_file_location("tiles2", Path(__file__).with_name("2_gbs_tiles.py"))
    t2 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(t2)
    layers = t2.find_layers(Path(hab_dir or core.HABITAT_DIR))
    tiles = core.Tiles(tdir or tiles_dir())
    ref = core.load_reference(names_csv=core.SOURCES / "typoch_names.csv")
    coef = ref["coef"]
    out_dir = Path(out_dir or Path(__file__).resolve().parent / "03_Validation")
    out_dir.mkdir(exist_ok=True)
    print(f"3_gbs_check.py - {core.VERSION}\nTiles: {tiles.dir.name}\n")

    tests = []
    for f in sorted((Path(__file__).resolve().parent / "01_Input").glob("*")):
        if f.suffix.lower() in (".kml", ".kmz", ".geojson", ".json"):
            for ft in core.read_features(f):
                tests.append(("input", f"{f.name}: {ft['name']}", ft["polys"]))
    rng = np.random.default_rng(SEED)
    tl = tiles.meta["tiles"]
    for kind, w, h in (("square 1 ha", 100, 100), ("square 10 ha", 316.2, 316.2), ("strip 15 m", 400, 15)):
        n = 0
        while n < N_EACH:
            e, nn = tl[rng.integers(len(tl))]
            cx, cy = e * 1000 + rng.uniform(300, 1700), nn * 1000 + rng.uniform(300, 1700)
            a = rng.uniform(0, np.pi)
            c, s = np.cos(a), np.sin(a)
            pts = [(-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2), (-w / 2, -h / 2)]
            ring = np.array([(cx + x * c - y * s, cy + x * s + y * c) for x, y in pts])
            tests.append((kind, f"{kind} #{n + 1} at {cx:.0f}/{cy:.0f}", [[ring]]))
            n += 1

    rows = []
    for i, (kind, label, polys) in enumerate(tests, 1):
        r = core.assess({"name": label, "polys": polys, "props": {}}, tiles, ref, rules=[])
        if r["terrestrial_ha"] < 0.5 * r["area_ha"] or r["nodata_ha"] > 0.01 * r["area_ha"]:
            continue                                              # mostly lake or outside the map
        ex, ea = exact(polys, layers, ref, coef)
        rows.append({"kind": kind, "label": label, "area_ha": r["area_ha"],
                     "msa_tile_central": r["central"]["msa"], "msa_exact_central": ex["central"],
                     "msa_tile_conservative": r["conservative"]["msa"], "msa_exact_conservative": ex["conservative"],
                     "terr_ha_tile": r["terrestrial_ha"], "terr_ha_exact": ea / 1e4})
        if i % 20 == 0:
            print(f"  {i}/{len(tests)}")
    stamp = time.strftime("%y%m%d")
    with open(out_dir / f"validation_{stamp}.csv", "w", encoding="utf-8", newline="") as fh:
        keys = list(rows[0].keys()) + ["diff_central", "diff_conservative"]
        fh.write(",".join(keys) + "\n")
        for r in rows:
            r["diff_central"] = r["msa_tile_central"] - r["msa_exact_central"]
            r["diff_conservative"] = r["msa_tile_conservative"] - r["msa_exact_conservative"]
            fh.write(",".join(f'"{r[k]}"' if k == "label" else f"{r[k]:.6f}" if isinstance(r[k], float)
                              else str(r[k]) for k in keys) + "\n")
    summ = {"date": time.strftime("%Y-%m-%d"), "tiles": tiles.dir.name, "res": tiles.res, "n": len(rows), "by_kind": {}}
    for kind in sorted({r["kind"] for r in rows}):
        d = np.array([abs(r["diff_central"]) for r in rows if r["kind"] == kind])
        summ["by_kind"][kind] = {"n": int(d.size), "mean_abs": float(d.mean()), "max_abs": float(d.max())}
        print(f"  {kind:14s} n={d.size:3d}  mean |diff| {d.mean():.4f}  largest {d.max():.4f}  (MSA units)")
    (out_dir / "validation_summary.json").write_text(json.dumps(summ, indent=1), encoding="utf-8")
    print(f"\nWritten: {out_dir / f'validation_{stamp}.csv'}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
    except SystemExit as e:
        if e.code not in (None, 0):
            print(e.code)
    except Exception:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("\nSomething went wrong - send Claude a screenshot of this window.")
    finally:
        if sys.stdin and sys.stdin.isatty():
            input("\nPress Enter to close.")
