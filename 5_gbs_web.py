#!/usr/bin/env python3
r"""
Web platform of the MSA parcel tool. Script 5 of 6. Double-click, or: python 5_gbs_web.py
Run again whenever the page, the tables or the tiles change.

What it does:
  1. Takes the page page\gbs_template.html and puts the reference tables (ref\*.csv), the official TypoCH
     names, the tile list, the validation (03_Validation\validation_summary.json), the official Habitat Map
     colours (FOEN/WSL symbology, for the legend) and the sample parcel (page\sample_mellingen.kml) into it.
  2. Writes the folder D:\NFA_data\4_projects\gbs_ch\web (outside OneDrive):
       index.html        the platform: upload KML, map, report, CSV/JSON downloads - all in the browser
       lib\              Leaflet plus proj4 (open source, bundled: no dependency on outside script servers)
       tiles\            habitat tiles (hard links to the tiles folder - no second copy on disk)
       ref\              the reference tables plus the validation table, for download
       sample_mellingen.kml
  3. No password: the page is public. Uploaded files never leave the browser of the user.

Then: 6_gbs_github.py publishes the web folder on GitHub Pages
      (https://naturefinanceaccelerator.github.io/nfa-gbs-ch/).
Test locally first: double-click start_local.bat in the web folder, or "python -m http.server" there.
"""
import json
import os
import shutil
import sys
import time
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gbs_core as core  # noqa: E402

HERE = Path(__file__).resolve().parent
OWNER, REPO = "naturefinanceaccelerator", "nfa-gbs-ch"
REPO_URL = f"https://github.com/{OWNER}/{REPO}"
SAMPLE = "sample_mellingen.kml"


def habitat_legend():
    """Official group colours of the Habitat Map (FOEN/WSL symbology v1.2, English QGIS style):
    [[label, "#rrggbb", [TypoCH values]], ...] in the official order. Empty list if not downloaded."""
    zips = sorted((core.SOURCES / "docs").glob("symbology*.zip"))
    if not zips:
        print("Legend: symbology not found (run 1_gbs_sources.py) - the page links to map.geo.admin.ch instead.")
        return []
    with zipfile.ZipFile(zips[-1]) as zf:
        name = next((n for n in zf.namelist() if n.endswith("_EN.qml")), None)
        if not name:
            return []
        root = ET.fromstring(zf.read(name))
    colours = {}
    for sym in root.iter("symbol"):
        for opt in sym.iter("Option"):
            if opt.get("name") == "color":
                colours.setdefault(sym.get("name"), opt.get("value"))
                break
    groups = {}
    for cat in root.iter("category"):
        col = colours.get(cat.get("symbol"))
        if not col:
            continue
        r, g, b = (int(x) for x in col.split(",")[:3])
        groups.setdefault(cat.get("label"), [cat.get("label"), f"#{r:02x}{g:02x}{b:02x}", []])[2].append(cat.get("value"))
    print(f"Legend: {len(groups)} habitat groups with official colours ({zips[-1].name})")
    return list(groups.values())


def link_or_copy(src, dst):
    if dst.exists():
        try:
            if os.path.samefile(src, dst):
                return False
        except OSError:
            pass
        if dst.stat().st_size == src.stat().st_size and dst.stat().st_mtime >= src.stat().st_mtime:
            return False
        dst.unlink()
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)
    return True


def main(tdir=None, out=None):
    found = sorted((core.WORK / "tiles").glob("*/meta.json"))
    tdir = Path(tdir or (found[-1].parent if found else ""))
    if not (tdir / "meta.json").exists():
        sys.exit("No habitat tiles found - run 2_gbs_tiles.py first.")
    out = Path(out or core.WORK / "web")
    print(f"5_gbs_web.py - {core.VERSION}\nTiles: {tdir.name}\nWeb folder: {out}\n")
    meta = json.loads((tdir / "meta.json").read_text(encoding="utf-8"))
    ref = core.load_reference(names_csv=core.SOURCES / "typoch_names.csv")
    vfile = HERE / "03_Validation" / "validation_summary.json"
    validation = json.loads(vfile.read_text(encoding="utf-8")) if vfile.exists() else None
    data = {
        "version": core.VERSION, "label": core.LABEL, "lv95": core.LV95_PROJ, "repo": REPO_URL,
        "sample": SAMPLE, "sample_kml": (HERE / "page" / SAMPLE).read_text(encoding="utf-8"),
        "hab_legend": habitat_legend(), "validation": validation, "ref": ref,
        "meta": {k: meta[k] for k in ("dataset", "res", "tile_m", "dtype", "codes", "pixels", "made")},
    }
    page = (HERE / "page" / "gbs_template.html").read_text(encoding="utf-8")
    page = page.replace("__LOGO__", (HERE / "page" / "nfa_logo.txt").read_text(encoding="utf-8").strip())
    page = page.replace("/*DATA*/", json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/"))
    out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(page, encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")                  # GitHub Pages: serve files as they are
    for f in (HERE / "page" / "lib").glob("*"):
        link_or_copy(f, out / "lib" / f.name)
    shutil.copy2(HERE / "page" / SAMPLE, out / SAMPLE)
    (out / "ref").mkdir(exist_ok=True)
    for f in list((HERE / "ref").glob("*.csv")) + sorted((HERE / "03_Validation").glob("validation_*.csv"))[-1:]:
        shutil.copy2(f, out / "ref" / f.name)
    shutil.copy2(tdir / "codes.csv", out / "ref" / "habitat_codes_switzerland.csv")
    print("Linking tiles ...")
    n = 0
    keep = set()
    for f in tdir.glob("*/*.bin"):
        dst = out / "tiles" / f.parent.name / f.name
        keep.add(dst)
        n += link_or_copy(f, dst)
    for old in (out / "tiles").glob("*/*.bin"):
        if old not in keep:
            old.unlink()
    (out / "start_local.bat").write_text(
        '@echo off\r\ncd /d "%~dp0"\r\nstart "" http://localhost:8765/\r\npython -m http.server 8765\r\n', encoding="utf-8")
    size = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    print(f"  {n} tiles new or changed, {len(keep)} in total")
    print(f"\nReady: {out}  ({size / 1e6:,.0f} MB, made {time.strftime('%d.%m.%Y %H:%M')})")
    print("Test: double-click start_local.bat in that folder. Publish: 6_gbs_github.py")
    if size > 950e6:
        print("WARNING: over 950 MB - GitHub Pages allows 1 GB per site.")


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
