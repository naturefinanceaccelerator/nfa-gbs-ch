#!/usr/bin/env python3
r"""
Reports for the KML files in 01_Input. Script 4 of 6. Double-click, or: python 4_gbs_report.py

Input:  01_Input\*.kml | *.kmz | *.geojson   one polygon or many. Polygon name = row name.
        Optional attributes per polygon (KML ExtendedData, GeoJSON properties, or a CSV with the same file name
        and a column "name"):
          target_habitat   TypoCH code of the target state, e.g. 4.2.4 (dry meadow) or 5.3 (hedge)
          target_from      only convert these habitats, e.g. 4.5 or 4.5;8.2 (default: the whole polygon)
          target_year      year the target is reached, e.g. 2035 (or a number of years, e.g. 10)
Output: 04_Output\<yymmdd>_<file name>\
          report.docx     Word report: key figures, habitat table per polygon, method, sources
          results.csv     one row per polygon (comma-separated, period decimals)
          habitats.csv    one row per polygon and habitat: every number behind the result
          result.json     everything, incl. data versions plus geometry checksums
          map.html        polygons on swisstopo maps, click for the numbers
Same engine as the web page (gbs_core.py): a polygon gives the same result in both.
Setup once: pip install python-docx pyproj
"""
import csv
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gbs_core as core  # noqa: E402

HERE = Path(__file__).resolve().parent
GREEN_DARK, GREEN, GREEN_LIGHT = "0C3024", "227766", "D3E7D1"


def need(pkg, mod):
    try:
        return __import__(mod)
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])
        return __import__(mod)


def tiles_dir():
    found = sorted((core.WORK / "tiles").glob("*/meta.json"))
    if not found:
        sys.exit("No habitat tiles found - run 2_gbs_tiles.py first.")
    return found[-1].parent


def f2(x, d=2):
    return core.fmt(x, d)


# ------------------------------------------------------------------ Word
def word(path, results, meta, ref, src_name, validation):
    need("python-docx", "docx")
    from docx import Document
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt, RGBColor, Cm

    doc = Document()
    for s in doc.sections:
        s.left_margin = s.right_margin = Cm(2.2)
        s.top_margin = s.bottom_margin = Cm(2.0)
    st = doc.styles["Normal"]
    st.font.name = "Aptos"
    st.font.size = Pt(11)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), "Aptos")
    for name, size in (("Title", 22), ("Heading 1", 15), ("Heading 2", 12.5)):
        h = doc.styles[name]
        h.font.name = "Aptos"
        h.font.size = Pt(size)
        h.font.bold = True
        h.font.color.rgb = RGBColor.from_string(GREEN_DARK)

    def shade(cell, hexcol):
        tcPr = cell._tc.get_or_add_tcPr()
        sh = OxmlElement("w:shd")
        sh.set(qn("w:val"), "clear")
        sh.set(qn("w:color"), "auto")
        sh.set(qn("w:fill"), hexcol)
        tcPr.append(sh)

    def table(head, rows, widths=None, right=()):
        t = doc.add_table(rows=1, cols=len(head))
        t.style = "Table Grid"
        t.alignment = WD_TABLE_ALIGNMENT.LEFT
        for i, h in enumerate(head):
            c = t.rows[0].cells[i]
            c.text = ""
            r = c.paragraphs[0].add_run(h)
            r.bold = True
            r.font.size = Pt(9)
            r.font.color.rgb = RGBColor(255, 255, 255)
            shade(c, GREEN)
        for row in rows:
            cells = t.add_row().cells
            for i, v in enumerate(row):
                cells[i].text = ""
                p = cells[i].paragraphs[0]
                run = p.add_run(str(v))
                run.font.size = Pt(9)
                if i in right:
                    p.alignment = 2
        if widths:
            t.autofit = False
            for row in t.rows:
                for i, w in enumerate(widths):
                    row.cells[i].width = Cm(w)
        return t

    doc.add_paragraph(f"MSA parcel report: {src_name}", style="Title")
    doc.add_paragraph(f"{core.LABEL} · Habitat Map of Switzerland {meta['dataset'].replace('HabitatMap_', '')} · "
                      f"NFA Foundation · {time.strftime('%d.%m.%Y')} · tool version {core.VERSION}")

    doc.add_heading("Summary", level=1)
    doc.add_paragraph("MSA (mean species abundance) is 1 for an intact ecosystem and 0 for one without its original "
                      "species. The footprint is the area-equivalent loss: 1 MSA.ha is one hectare fully degraded. "
                      "Central uses the GLOBIO4 classes. Conservative uses a stricter class where the habitat is managed.")
    rows = []
    for r in results:
        c, k = r["central"], r["conservative"]
        rows.append([r["name"], f2(r["area_ha"]), f2(c["msa"], 3), f2(k["msa"], 3), f2(c["footprint_msa_ha"]),
                     f2(k["footprint_msa_ha"]), f2(c.get("gain_msa_ha")), f2(k.get("gain_msa_ha"))])
    table(["Polygon", "Area ha", "MSA central", "MSA cons.", "Footprint MSA.ha central", "Footprint MSA.ha cons.",
           "Gain MSA.ha central", "Gain MSA.ha cons."], rows, right=range(1, 8))
    tot = {v: sum(r[v]["footprint_msa_ha"] for r in results) for v in ("central", "conservative")}
    doc.add_paragraph(f"Total footprint: {f2(tot['central'])} MSA.ha central, {f2(tot['conservative'])} MSA.ha "
                      f"conservative ({f2(tot['central'] / 100, 4)} and {f2(tot['conservative'] / 100, 4)} MSA.km²).")

    for r in results:
        doc.add_heading(r["name"], level=1)
        c, k = r["central"], r["conservative"]
        doc.add_paragraph(f"Area {f2(r['area_ha'], 3)} ha, of which terrestrial {f2(r['terrestrial_ha'], 3)} ha, "
                          f"open water {f2(r['water_ha'], 3)} ha, outside the Habitat Map {f2(r['nodata_ha'], 3)} ha. "
                          "Pixels counted: " + f"{r['pixels']:,}".replace(",", "’") + f" at {r['pixel_area_m2']:g} m² " +
                          f"(area correction factor {r['scale']:.4f}). Geometry SHA-256: {r['geom_sha256'][:16]}…")
        table(["", "Central", "Conservative"], [
            ["MSA birds & mammals", f2(c["msa_wb"], 3), f2(k["msa_wb"], 3)],
            ["MSA plants", f2(c["msa_pl"], 3), f2(k["msa_pl"], 3)],
            ["MSA overall (mean of both)", f2(c["msa"], 3), f2(k["msa"], 3)],
            ["Footprint MSA.ha = Σ area × (1 − MSA)", f2(c["footprint_msa_ha"], 3), f2(k["footprint_msa_ha"], 3)],
            ["Intact-equivalent MSA.ha = Σ area × MSA", f2(c["intact_msa_ha"], 3), f2(k["intact_msa_ha"], 3)],
        ] + ([["Target MSA", f2(c["msa_target"], 3), f2(k["msa_target"], 3)],
              ["Gain MSA.ha = Σ area × (MSA target − MSA now)", f2(c["gain_msa_ha"], 3), f2(k["gain_msa_ha"], 3)],
              [f"Gain per year ({c['years']} years, linear)", f2(c["gain_msa_ha_per_year"], 3),
               f2(k["gain_msa_ha_per_year"], 3)]] if r["rules"] else []), widths=[8, 3.5, 3.5], right=(1, 2))
        if r["rules"]:
            doc.add_paragraph("Target: " + "; ".join(
                f"{'whole polygon' if x['from'] == '*' else 'TypoCH ' + x['from']} → TypoCH {x['to']} "
                f"({core.habitat_name(x['to'], ref)})" for x in r["rules"]) + f", reached {r['target_year']}.")
        doc.add_heading("Habitats", level=2)
        rows = []
        for p in sorted(r["pieces"], key=lambda p: -p["area_ha"]):
            c_, k_ = p["central"], p["conservative"]
            rows.append([p["typoch"], p["name"], f2(p["area_ha"], 3),
                         f"{c_['globio']} · {f2(c_['msa'], 3)}" if p["terrestrial"] else "water",
                         f"{k_['globio']} · {f2(k_['msa'], 3)}" if p["terrestrial"] else "–",
                         f2(p["area_ha"] * (1 - c_["msa"]), 3) if p["terrestrial"] else "–",
                         p["target"]["typoch"] if "target" in p else ""])
        table(["TypoCH", "Habitat", "ha", "GLOBIO · MSA central", "GLOBIO · MSA cons.", "Footprint central",
               "Target"], rows, widths=[1.6, 5.2, 1.6, 2.6, 2.6, 2, 1.4], right=(2, 5))

    doc.add_heading("Method", level=1)
    for t in [
        "Polygons are read from the KML (WGS84) and projected to Swiss LV95 (EPSG:2056). Areas are planar LV95 areas.",
        f"Habitat: Habitat Map of Switzerland {meta['dataset'].replace('HabitatMap_', '')} (FOEN/WSL, ground cover layer), "
        f"burnt into {meta['res']:g} m tiles. A pixel counts when its centre lies inside the polygon. Habitat shares come "
        "from the pixels. The area of each habitat is the polygon area times its share.",
        "Each TypoCH code is mapped to one GLOBIO land-use class (longest matching code, table below). The GLOBIO class "
        "gives the MSA of birds & mammals and of plants (GLOBIOweb technical documentation, PBL 2023, Table 3.1). "
        "MSA overall is the mean of both groups, as in the GLOBIO4 code (CalcLanduseMSA).",
        "Open water is outside the terrestrial MSA (GLOBIO treats freshwater in a separate module).",
        "Footprint = Σ area × (1 − MSA). Gain = Σ area × (MSA target − MSA now). Gain per year assumes a linear path.",
        "Conservative variant: managed near-natural forest at 0.70 and sealed surfaces at 0.05 (GLOBIO 3.5, PBL 2016, "
        "Table 2.2); mown semi-natural grassland as extensive rangeland; arable land as intensive cropland.",
    ]:
        doc.add_paragraph(t, style="List Bullet")
    if validation:
        vk = validation["by_kind"]
        doc.add_paragraph("Validation against an exact polygon overlay (3_gbs_check.py, " + validation["date"] + "): " +
                          "; ".join(f"{k}: mean difference {core.fmt(v['mean_abs'])}, largest {core.fmt(v['max_abs'])} MSA (n={v['n']})"
                                    for k, v in vk.items()) + ".")
    doc.add_heading("Not included", level=2)
    for t in ["Road and rail disturbance, fragmentation (GLOBIO infrastructure modules) - phase 2.",
              "Nitrogen deposition, climate change, hunting: constant or not relevant at parcel scale.",
              "Single trees and shrubs outside forest (separate Habitat Map layer).",
              "MSA is modelled from habitat type, not measured. Field monitoring proves the change."]:
        doc.add_paragraph(t, style="List Bullet")
    doc.add_heading("Mapping TypoCH to GLOBIO", level=2)
    table(["TypoCH", "Habitat", "Central", "Conservative"],
          [[m["t"], m["name"], f"{m['c']} · {f2(ref['coef'][m['c']]['msa'], 3) if m['terr'] else 'water'}",
            f"{m['k']} · {f2(ref['coef'][m['k']]['msa'], 3) if m['terr'] else 'water'}"] for m in ref["mapping"]],
          widths=[1.6, 7, 3.2, 3.2])
    doc.add_heading("Sources", level=2)
    for t in ["PBL (2023): Technical documentation of the GLOBIOweb datasets. globio.info",
              "GLOBIO4 model code: github.com/GLOBIO4/GlobioModelPublic",
              "Schipper A. M. et al. (2020): Projecting terrestrial biodiversity intactness with GLOBIO 4. "
              "Global Change Biology 26: 760–771",
              "PBL (2016): The GLOBIO model. A technical description of version 3.5",
              "Price B. et al. (2025): The Habitat Map of Switzerland v1_2 2025. EnviDat, doi:10.16904/envidat.723. "
              "Source: FOEN/WSL",
              "Delarze R., Gonseth Y., Eggenberg S., Vust M. (2015): Lebensräume der Schweiz. hep, Bern",
              "Code, tables plus validation: github.com/naturefinanceaccelerator/nfa-gbs-ch"]:
        doc.add_paragraph(t, style="List Bullet")
    doc.add_paragraph(f"Results are labelled “{core.LABEL}”. They are not the official Global Biodiversity Score (GBS) "
                      "of CDC Biodiversité, which uses an adapted GLOBIO 3.6.")
    doc.save(path)


# ------------------------------------------------------------------ map
def map_html(path, feats, results):
    import json as js
    data = []
    for f, r in zip(feats, results):
        data.append({"name": f["name"], "polys": [[[list(p) for p in ring] for ring in poly] for poly in f["polys_wgs"]],
                     "ha": round(r["area_ha"], 3), "msa": round(r["central"]["msa"] or 0, 3),
                     "msak": round(r["conservative"]["msa"] or 0, 3), "fp": round(r["central"]["footprint_msa_ha"], 3)})
    html = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>MSA parcels</title><link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.css">
<style>html,body,#m{height:100%;margin:0;font:13px Aptos,Segoe UI,Arial,sans-serif}</style></head><body><div id="m"></div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.js"></script><script>
const D=__D__;const m=L.map('m');
L.tileLayer('https://wmts.geo.admin.ch/1.0.0/ch.swisstopo.pixelkarte-grau/default/current/3857/{z}/{x}/{y}.jpeg',{maxZoom:19,attribution:'© swisstopo'}).addTo(m);
const g=L.featureGroup().addTo(m);
for(const d of D){for(const p of d.polys){L.polygon(p.map(r=>r.map(([x,y])=>[y,x])),{color:'#0C3024',weight:2,fillColor:'#227766',fillOpacity:.25})
.bindPopup(`<b>${d.name}</b><br>${d.ha} ha<br>MSA central ${d.msa}, conservative ${d.msak}<br>Footprint ${d.fp} MSA.ha (central)`).addTo(g)}}
m.fitBounds(g.getBounds(),{padding:[30,30]});
</script></body></html>"""
    Path(path).write_text(html.replace("__D__", js.dumps(data)), encoding="utf-8")


def main(tdir=None, inp=None, outp=None):
    tiles = core.Tiles(tdir or tiles_dir())
    ref = core.load_reference(names_csv=core.SOURCES / "typoch_names.csv")
    inp = Path(inp or HERE / "01_Input")
    outp = Path(outp or HERE / "04_Output")
    vfile = HERE / "03_Validation" / "validation_summary.json"
    validation = json.loads(vfile.read_text(encoding="utf-8")) if vfile.exists() else None
    files = [f for f in sorted(inp.glob("*")) if f.suffix.lower() in (".kml", ".kmz", ".geojson", ".json")]
    print(f"4_gbs_report.py - {core.VERSION}\nTiles: {tiles.dir.name}\nInput: {len(files)} file(s) in {inp}\n")
    if not files:
        print("Nothing in 01_Input - put a KML, KMZ or GeoJSON there for reports.")
        return
    for f in files:
        feats = core.read_features(f)
        results = [core.assess(ft, tiles, ref) for ft in feats]
        out = outp / f"{time.strftime('%y%m%d')}_{f.stem}"
        out.mkdir(parents=True, exist_ok=True)
        with open(out / "results.csv", "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["name", "area_ha", "terrestrial_ha", "water_ha", "nodata_ha",
                        "msa_central", "msa_wb_central", "msa_plants_central", "footprint_msa_ha_central",
                        "msa_conservative", "footprint_msa_ha_conservative", "target", "target_year",
                        "gain_msa_ha_central", "gain_msa_ha_conservative", "gain_per_year_central", "geom_sha256"])
            for r in results:
                c, k = r["central"], r["conservative"]
                w.writerow([r["name"], f"{r['area_ha']:.4f}", f"{r['terrestrial_ha']:.4f}", f"{r['water_ha']:.4f}",
                            f"{r['nodata_ha']:.4f}", f"{c['msa']:.4f}", f"{c['msa_wb']:.4f}", f"{c['msa_pl']:.4f}",
                            f"{c['footprint_msa_ha']:.4f}", f"{k['msa']:.4f}", f"{k['footprint_msa_ha']:.4f}",
                            "; ".join(f"{x['from']}>{x['to']}" for x in r["rules"]), r["target_year"],
                            "" if c.get("gain_msa_ha") is None else f"{c['gain_msa_ha']:.4f}",
                            "" if k.get("gain_msa_ha") is None else f"{k['gain_msa_ha']:.4f}",
                            "" if c.get("gain_msa_ha_per_year") is None else f"{c['gain_msa_ha_per_year']:.4f}",
                            r["geom_sha256"]])
        with open(out / "habitats.csv", "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["polygon", "typoch", "habitat", "mapping_row", "area_ha", "pixels", "terrestrial",
                        "globio_central", "msa_wb_central", "msa_plants_central", "msa_central",
                        "globio_conservative", "msa_conservative", "footprint_msa_ha_central", "target_typoch",
                        "msa_target_central"])
            for r in results:
                for p in r["pieces"]:
                    c, k = p["central"], p["conservative"]
                    t = p.get("target")
                    w.writerow([r["name"], p["typoch"], p["name"], p["row"], f"{p['area_ha']:.5f}", p["pixels"],
                                int(p["terrestrial"]), c["globio"], c["wb"] if c["wb"] is not None else "",
                                c["pl"] if c["pl"] is not None else "", "" if c["msa"] is None else f"{c['msa']:.4f}",
                                k["globio"], "" if k["msa"] is None else f"{k['msa']:.4f}",
                                f"{p['area_ha'] * (1 - c['msa']):.5f}" if p["terrestrial"] else "",
                                t["typoch"] if t else "", f"{t['central']['msa']:.4f}" if t else ""])
        (out / "result.json").write_text(json.dumps({
            "tool": core.VERSION, "label": core.LABEL, "made": time.strftime("%Y-%m-%d %H:%M"), "input": f.name,
            "habitat_map": tiles.meta["dataset"], "tiles": tiles.dir.name, "res_m": tiles.res,
            "validation": validation, "results": results}, ensure_ascii=False, indent=1), encoding="utf-8")
        word(out / "report.docx", results, tiles.meta, ref, f.stem, validation)
        map_html(out / "map.html", feats, results)
        print(f"  {f.name}: {len(results)} polygon(s) -> {out}")
        for r in results:
            print(f"     {r['name']}: {r['area_ha']:.2f} ha, MSA {r['central']['msa']:.2f} "
                  f"(conservative {r['conservative']['msa']:.2f}), footprint {r['central']['footprint_msa_ha']:.2f} MSA.ha")
    if sys.platform == "win32" and __name__ == "__main__":
        import os
        os.startfile(out)  # noqa: S606


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
