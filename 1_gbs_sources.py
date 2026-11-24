#!/usr/bin/env python3
r"""
Reference sources for the MSA parcel tool. Script 1 of 6. Double-click, or: python 1_gbs_sources.py
Run once, then again whenever you want fresh copies. Skips files that are already there.

Downloads into D:\NFA_data\1_sources\gbs (raw data stays outside OneDrive):
  repos\    GLOBIO4 model code (PBL, GitHub) - source of the overall-MSA rule and the pressure coefficients
  docs\     GLOBIOweb technical documentation (Table 3.1 = land-use MSA), GLOBIO 3.5 technical description,
            Habitat Map of Switzerland v1.2 data description, TypoCH lookup tables, symbology
  sources_manifest.csv   every file with its URL, date, size, SHA-256 (proof of which version was used)
  typoch_names.csv       official German TypoCH names, read from the WSL lookup table (used in reports)

The Habitat Map itself is already in D:\NFA_data\1_sources\bafu\lebensraumkarte-schweiz - not downloaded again.
Setup once: pip install requests
Next: 2_gbs_tiles.py
"""
import csv
import hashlib
import io
import re
import sys
import time
import zipfile
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gbs_core as core  # noqa: E402

ENVIDAT = "https://www.envidat.ch/dataset/d6182107-2086-49c0-97dd-f3a77056157c/resource"
FILES = [   # (folder, file name, URL, what it is)
    ("repos", "GlobioModelPublic-main.zip", "https://github.com/GLOBIO4/GlobioModelPublic/archive/refs/heads/main.zip",
     "GLOBIO4 model code (PBL). CalcLanduseMSA: overall = (birds & mammals + plants) / 2"),
    ("docs", "GlobioWeb_technical_documentation_20230219.pdf",
     "https://www.globio.info/wp-content/uploads/2023/03/GlobioWeb_technical_documentation_20230219.pdf",
     "GLOBIOweb technical documentation (PBL 2023). Table 3.1: land-use MSA per class"),
    ("docs", "PBL_2016_GLOBIO_3.5_technical_description.pdf", "https://pbl.nl/downloads/pbl-publication-2369pdf",
     "The GLOBIO model, technical description of version 3.5 (PBL 2016). Table 2.2 (conservative variant)"),
    ("docs", "Schipper_etal_2020_README.txt", "https://dataportaal.pbl.nl/data/GLOBIO/Schipper_etal_2020/README.txt",
     "GLOBIO4 data release, Schipper et al. 2020, Global Change Biology 26: 760-771"),
    ("docs", "Data_Description_Lebensraumkarte_v1_2_Dec2025.pdf",
     f"{ENVIDAT}/564b16e5-0523-4431-94bc-3e6d1415c5a1/download/data_description_lebensraumkarte_v1_2_dec2025.pdf",
     "Habitat Map of Switzerland v1.2, data description (WSL 2025)"),
    ("docs", "TypoCH_NUM_LookupTable_26112025.csv",
     f"{ENVIDAT}/28aace15-eb00-4ec2-98ef-b55acc18286f/download/typoch_num_lookuptable_26112025.csv",
     "Habitat Map v1.2: TypoCH codes with names (DE, FR, IT)"),
    ("docs", "LUT_einzelbaum_gebuesch_v_1_0.csv",
     f"{ENVIDAT}/0035dd77-ea6d-4d3a-89bd-3ad6ee36302e/download/lut_einzelbaum_gebuesch_v_1_0.csv",
     "Habitat Map v1.2: lookup table of the single trees and shrubs layer"),
    ("docs", "symbology_v1_2_2025.zip", f"{ENVIDAT}/47c0e914-986f-4ad3-9bcf-49160023c030/download/symbology_v1_2_2025.zip",
     "Habitat Map v1.2: official colours (QGIS, ArcGIS)"),
]
LINKS = [   # not downloadable as a file - listed in the manifest only
    ("GBS open wiki (CDC Biodiversité)", "https://cdc-biodiversite.notion.site/GBS-open-Wiki-2a380e7be7c74648b2f6f581c26cc852"),
    ("GBS documentation (CDC Biodiversité)", "https://www.cdc-biodiversite.fr/documentation-gbs/"),
    ("GLOBIO4 wiki", "https://github.com/GLOBIO4/GlobioModelPublic/wiki"),
    ("Habitat Map v1.2 on EnviDat (DOI 10.16904/envidat.723)", "https://www.envidat.ch/#/metadata/the-habitat-map-of-switzerland-v1_2-2025"),
    ("Habitat Map on geo.admin.ch (STAC)", "https://data.geo.admin.ch/browser/index.html#/collections/ch.bafu.lebensraumkarte-schweiz"),
]
UA = {"User-Agent": "NFA-MSA-parcel-tool/1.0 (+https://github.com/naturefinanceaccelerator/nfa-gbs-ch)"}


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def names_from_lut(lut, out):
    """Official TypoCH names: picks the code column and the German name column, whatever their exact header."""
    raw = lut.read_bytes()
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    dialect = csv.Sniffer().sniff(text.splitlines()[0], delimiters=",;\t")
    rows = list(csv.DictReader(io.StringIO(text), dialect=dialect))
    cols = rows[0].keys()
    code = next((c for c in cols if c.strip().lower() == "typoch"), None) or \
        next((c for c in cols if "typoch" in c.lower() and "num" not in c.lower() and "_" not in c), None)
    num = next((c for c in cols if "num" in c.lower()), None)
    de = next((c for c in cols if c.lower().endswith("_de") or c.lower() in ("de", "name_de", "typoch_de")), None)
    if not de or not (code or num):
        print(f"  lookup table columns not recognised: {list(cols)} - names stay as in ref\\typoch_globio_mapping.csv")
        return 0
    n = 0
    with open(out, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["typoch", "name_de", "typoch_map"])
        for r in rows:
            c = (r.get(code) if code else "") or r.get(num, "")
            if c and r.get(de):
                w.writerow([core.dotted(c), r[de].strip(), c.strip()])
                n += 1
    return n


def main(dest=None):
    dest = Path(dest or core.SOURCES)
    print(f"1_gbs_sources.py - {core.VERSION}\nFolder: {dest}\n")
    rows = []
    for folder, name, url, what in FILES:
        p = dest / folder / name
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists():
            try:
                r = requests.get(url, headers=UA, timeout=120)
                r.raise_for_status()
                p.write_bytes(r.content)
                print(f"  downloaded  {name}  ({len(r.content) / 1e6:.1f} MB)")
            except Exception as e:  # noqa: BLE001
                print(f"  FAILED      {name}: {e}")
                rows.append([what, url, "", "", "", "failed"])
                continue
        else:
            print(f"  present     {name}")
        rows.append([what, url, str(p.relative_to(dest)), p.stat().st_size, sha(p),
                     time.strftime("%Y-%m-%d", time.localtime(p.stat().st_mtime))])
        if name.endswith("main.zip"):
            target = p.parent / "GlobioModelPublic"
            if not target.exists():
                with zipfile.ZipFile(p) as z:
                    z.extractall(p.parent)
                (p.parent / "GlobioModelPublic-main").rename(target)
    for what, url in LINKS:
        rows.append([what, url, "", "", "", "link only"])
    with open(dest / "sources_manifest.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["what", "url", "file", "bytes", "sha256", "date"])
        w.writerows(rows)
    lut = dest / "docs" / "TypoCH_NUM_LookupTable_26112025.csv"
    if lut.exists():
        n = names_from_lut(lut, dest / "typoch_names.csv")
        print(f"\nOfficial TypoCH names: {n} codes -> {dest / 'typoch_names.csv'}")
    print(f"Manifest: {dest / 'sources_manifest.csv'}")


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
