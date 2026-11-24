r"""
gbs_core.py - shared engine of the Swiss MSA parcel tool. Not run on its own: the numbered scripts import it.

One method, two front ends: the web page (page\gbs_template.html, JavaScript) and the scripts (Python)
apply the SAME steps in the SAME order, so a parcel gives the same number in both:

  1. Read the polygon (KML, KMZ, GeoJSON). WGS84 -> LV95 (EPSG:2056) with the proj string LV95 below.
  2. Pixel-centre rule: a habitat-map pixel counts when its centre lies inside the polygon (even-odd rule).
     Habitat tiles: TypoCH code per pixel, RES_M metres, TILE_M x TILE_M metres per tile, north-up.
  3. Shares from pixels, area from geometry: area per habitat = polygon area (shoelace, LV95) x pixel share.
  4. TypoCH code -> GLOBIO class (ref\typoch_globio_mapping.csv, longest matching code prefix).
  5. GLOBIO class -> MSA birds & mammals, MSA plants (ref\globio_msa_coefficients.csv).
     MSA overall = (MSA birds & mammals + MSA plants) / 2   (GLOBIO4 CalcLanduseMSA).
  6. Open water is not terrestrial: reported, but outside the MSA area.
  7. Footprint (MSA.ha) = sum(area_ha x (1 - MSA)).  Gain (MSA.ha) = sum(area_ha x (MSA target - MSA now)).
Two variants: central (GLOBIO4 classes) and conservative (stricter class per habitat). Both always reported.
"""
import hashlib
import json
import math
import re
import time
import zipfile
import zlib
from pathlib import Path
from xml.etree import ElementTree as ET

import numpy as np

VERSION = "1.0 (19.11.2026)"
LV95_PROJ = ("+proj=somerc +lat_0=46.9524055555556 +lon_0=7.43958333333333 +k_0=1 +x_0=2600000 +y_0=1200000 "
             "+ellps=bessel +towgs84=674.374,15.056,405.346,0,0,0,0 +units=m +no_defs")
RES_M = 2.0            # habitat tile pixel size (m). Validation: 3_gbs_check.py
TILE_M = 2000          # tile edge (m)
LABEL = "GBS-consistent MSA (GLOBIO4 land-use module)"

HERE = Path(__file__).resolve().parent
REF = HERE / "ref"


def nfa_data():
    """D:\\NFA_data (external disk), else C:\\NFA_data."""
    for p in (Path(r"D:\NFA_data"), Path(r"C:\NFA_data")):
        if p.exists():
            return p
    return Path(r"D:\NFA_data")


NFA_DATA = nfa_data()
WORK = NFA_DATA / "4_projects" / "gbs_ch"                       # tiles, web, git - outside OneDrive
SOURCES = NFA_DATA / "1_sources" / "gbs"                         # downloaded references (1_gbs_sources.py)
HABITAT_DIR = NFA_DATA / "1_sources" / "bafu" / "lebensraumkarte-schweiz"


# ------------------------------------------------------------------ reference tables
def read_csv(path):
    import csv
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def load_reference(ref_dir=REF, names_csv=None):
    """Mapping, coefficients, names. Returns a dict that is also written into the web page."""
    coef = {}
    for r in read_csv(Path(ref_dir) / "globio_msa_coefficients.csv"):
        wb = float(r["msa_birds_mammals"]) if r["msa_birds_mammals"] else None
        pl = float(r["msa_plants"]) if r["msa_plants"] else None
        coef[r["globio_code"]] = {"name": r["globio_class"], "wb": wb, "pl": pl,
                                  "msa": (wb + pl) / 2 if wb is not None else None,
                                  "model": r["model"], "src": r["source"], "note": r["note"]}
    mapping = []
    for r in read_csv(Path(ref_dir) / "typoch_globio_mapping.csv"):
        for k in ("globio_central", "globio_conservative"):
            if r[k] not in coef:
                raise ValueError(f"Mapping {r['typoch']}: GLOBIO class {r[k]} not in coefficient table")
        mapping.append({"t": r["typoch"], "name": r["name_de"], "terr": r["terrestrial"] == "1",
                        "c": r["globio_central"], "k": r["globio_conservative"],
                        "wc": r["why_central"], "wk": r["why_conservative"]})
    names = {}
    if names_csv and Path(names_csv).exists():
        for r in read_csv(names_csv):
            names[r["typoch"]] = r["name_de"]
    return {"coef": coef, "mapping": mapping, "names": names}


def dotted(code):
    """Habitat Map code -> dotted TypoCH: '4.5.1' stays, 'STR1112' -> '1.1.1.2', '1.1.x' -> '1.1', 45 -> '4.5'."""
    s = str(code).strip()
    if s.upper().startswith("STR") or re.fullmatch(r"\d+", s):
        s = ".".join(re.sub(r"\D", "", s))
    s = re.sub(r"(\.[xX])+$", "", s)
    return s


def match_row(code, mapping):
    """Longest mapping row whose code is a prefix (by level) of the habitat code."""
    parts = dotted(code).split(".")
    best = None
    for row in mapping:
        rp = row["t"].split(".")
        if parts[:len(rp)] == rp and (best is None or len(rp) > len(best["t"].split("."))):
            best = row
    return best


def habitat_name(code, ref):
    d = dotted(code)
    if d in ref["names"]:
        return ref["names"][d]
    row = match_row(d, ref["mapping"])
    if row and row["t"] == d:
        return row["name"]
    return row["name"] if row else f"TypoCH {d}"


# ------------------------------------------------------------------ geometry input
def _proj():
    from pyproj import Transformer
    return Transformer.from_crs("EPSG:4326", LV95_PROJ, always_xy=True)


def _coords(text):
    pts = []
    for tok in (text or "").replace("\n", " ").split():
        v = tok.split(",")
        if len(v) >= 2:
            pts.append((float(v[0]), float(v[1])))
    return pts


def _strip(tag):
    return tag.rsplit("}", 1)[-1]


def read_kml_bytes(data):
    root = ET.fromstring(data)
    feats = []
    for pm in root.iter():
        if _strip(pm.tag) != "Placemark":
            continue
        name, props, polys = "", {}, []
        for el in pm.iter():
            t = _strip(el.tag)
            if t == "name" and not name:
                name = (el.text or "").strip()
            elif t == "Data":
                v = [c for c in el if _strip(c.tag) == "value"]
                props[el.get("name", "")] = (v[0].text or "").strip() if v else ""
            elif t == "SimpleData":
                props[el.get("name", "")] = (el.text or "").strip()
            elif t == "Polygon":
                rings = []
                for b in el:
                    bt = _strip(b.tag)
                    if bt in ("outerBoundaryIs", "innerBoundaryIs"):
                        for c in b.iter():
                            if _strip(c.tag) == "coordinates":
                                ring = _coords(c.text)
                                if len(ring) >= 3:
                                    rings.insert(0, ring) if bt == "outerBoundaryIs" else rings.append(ring)
                if rings:
                    polys.append(rings)
        if polys:
            feats.append({"name": name, "props": props, "polys_wgs": polys})
    return feats


def read_geojson_bytes(data):
    gj = json.loads(data)
    items = gj["features"] if gj.get("type") == "FeatureCollection" else [gj]
    feats = []
    for i, f in enumerate(items):
        g = f.get("geometry") or {}
        props = {k: ("" if v is None else str(v)) for k, v in (f.get("properties") or {}).items()}
        polys = []
        if g.get("type") == "Polygon":
            polys = [[[tuple(p[:2]) for p in r] for r in g["coordinates"]]]
        elif g.get("type") == "MultiPolygon":
            polys = [[[tuple(p[:2]) for p in r] for r in poly] for poly in g["coordinates"]]
        if polys:
            name = props.get("name") or props.get("Name") or props.get("NAME") or f"Polygon {i + 1}"
            feats.append({"name": name, "props": props, "polys_wgs": polys})
    return feats


def read_features(path):
    """KML, KMZ, GeoJSON -> features with LV95 rings. A CSV with the same name adds attributes by name."""
    path = Path(path)
    ext = path.suffix.lower()
    if ext == ".kmz":
        with zipfile.ZipFile(path) as z:
            kml = [n for n in z.namelist() if n.lower().endswith(".kml")]
            feats = read_kml_bytes(z.read(kml[0]))
    elif ext == ".kml":
        feats = read_kml_bytes(path.read_bytes())
    elif ext in (".geojson", ".json"):
        feats = read_geojson_bytes(path.read_bytes())
    else:
        raise ValueError(f"{path.name}: only KML, KMZ or GeoJSON")
    side = path.with_suffix(".csv")
    if side.exists():
        extra = {r.get("name", "").strip(): r for r in read_csv(side)}
        for f in feats:
            f["props"].update({k: v for k, v in extra.get(f["name"], {}).items() if k != "name" and v})
    tr = _proj()
    for i, f in enumerate(feats):
        f["name"] = f["name"] or f"Polygon {i + 1}"
        f["polys"] = []
        for poly in f["polys_wgs"]:
            rings = []
            for ring in poly:
                lon, lat = zip(*ring)
                x, y = tr.transform(lon, lat)
                rings.append(np.column_stack([x, y]))
            f["polys"].append(rings)
    return feats


def ring_area(r):
    x, y = r[:, 0], r[:, 1]
    return 0.5 * abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))


def geom_area(polys):
    return sum(ring_area(p[0]) - sum(ring_area(h) for h in p[1:]) for p in polys)


def geom_hash(polys):
    """SHA-256 of the LV95 coordinates rounded to 1 cm - identifies the exact geometry in the report."""
    s = ";".join("|".join(",".join(f"{x:.2f} {y:.2f}" for x, y in r) for r in p) for p in polys)
    return hashlib.sha256(s.encode()).hexdigest()


# ------------------------------------------------------------------ habitat tiles
class Tiles:
    """Reads the habitat tiles written by 2_gbs_tiles.py (zlib-compressed uint8/uint16, north-up)."""

    def __init__(self, folder):
        self.dir = Path(folder)
        self.meta = json.loads((self.dir / "meta.json").read_text(encoding="utf-8"))
        self.res = self.meta["res"]
        self.tile = self.meta["tile_m"]
        self.n = int(round(self.tile / self.res))
        self.dtype = np.uint16 if self.meta.get("dtype") == "uint16" else np.uint8
        self.codes = self.meta["codes"]
        self.cache = {}

    def get(self, e0, n0):
        key = (e0, n0)
        if key not in self.cache:
            p = self.dir / str(e0 // 1000) / f"{n0 // 1000}.bin"
            a = None
            if p.exists():
                a = np.frombuffer(zlib.decompress(p.read_bytes()), dtype=self.dtype).reshape(self.n, self.n)
            if len(self.cache) > 400:
                self.cache.clear()
            self.cache[key] = a
        return self.cache[key]


def pixel_counts(polys, tiles, keep_mask=False):
    """Pixel-centre rule, even-odd over all rings. Same arithmetic as countPixels() in the web page.
    Returns {code index: pixels} (0 = no data) and optionally the pixel runs for drawing."""
    res, T = tiles.res, tiles.tile
    edges = []
    for p in polys:
        for r in p:
            a = np.asarray(r, float)
            b = np.roll(a, -1, axis=0)
            edges.append(np.column_stack([a, b]))
    E = np.vstack(edges)                                     # x1 y1 x2 y2
    E = E[E[:, 1] != E[:, 3]]
    xmin, ymin = float(min(E[:, 0].min(), E[:, 2].min())), float(min(E[:, 1].min(), E[:, 3].min()))
    xmax, ymax = float(max(E[:, 0].max(), E[:, 2].max())), float(max(E[:, 1].max(), E[:, 3].max()))
    counts = {}
    runs = [] if keep_mask else None
    for te in range(int(math.floor(xmin / T)) * T, int(math.floor(xmax / T)) * T + T, T):
        for tn in range(int(math.floor(ymin / T)) * T, int(math.floor(ymax / T)) * T + T, T):
            top = tn + T
            r0 = max(0, math.ceil((top - ymax) / res - 0.5))
            r1 = min(tiles.n - 1, math.floor((top - ymin) / res - 0.5))
            if r1 < r0:
                continue
            arr = tiles.get(te, tn)
            for row in range(r0, r1 + 1):
                yc = top - (row + 0.5) * res
                sel = ((E[:, 1] <= yc) & (yc < E[:, 3])) | ((E[:, 3] <= yc) & (yc < E[:, 1]))
                if not sel.any():
                    continue
                e = E[sel]
                xs = np.sort(e[:, 0] + (yc - e[:, 1]) * (e[:, 2] - e[:, 0]) / (e[:, 3] - e[:, 1]))
                for k in range(0, len(xs) - 1, 2):
                    c0 = max(0, math.ceil((xs[k] - te) / res - 0.5))
                    c1 = min(tiles.n - 1, math.ceil((xs[k + 1] - te) / res - 0.5) - 1)
                    if c1 < c0:
                        continue
                    if arr is None:
                        counts[0] = counts.get(0, 0) + (c1 - c0 + 1)
                        vals = None
                    else:
                        vals = arr[row, c0:c1 + 1]
                        u, n = np.unique(vals, return_counts=True)
                        for a, b in zip(u.tolist(), n.tolist()):
                            counts[a] = counts.get(a, 0) + b
                    if keep_mask:
                        runs.append((te, top, row, c0, c1, vals))
    return counts, runs


# ------------------------------------------------------------------ MSA
def parse_rules(props, ref):
    """Target from polygon attributes: target_habitat (TypoCH code), optional target_from (code prefixes,
    separated by ; or ,), target_year. Returns rules [(from prefix or '*', to code)], year."""
    to = (props.get("target_habitat") or props.get("target") or "").strip()
    rules = []
    if to:
        frm = [s.strip() for s in re.split(r"[;,]", props.get("target_from", "") or "") if s.strip()] or ["*"]
        rules = [(dotted(f) if f != "*" else "*", dotted(to)) for f in frm]
    yr = props.get("target_year") or props.get("years") or ""
    return rules, yr


def rule_target(code_d, rules):
    parts = code_d.split(".")
    for frm, to in rules:
        if frm == "*" or parts[:len(frm.split("."))] == frm.split("."):
            return to
    return None


def assess(feat, tiles, ref, rules=None, year_now=None):
    """All numbers for one polygon. Every intermediate value is kept for the report."""
    year_now = year_now or int(time.strftime("%Y"))
    counts, _ = pixel_counts(feat["polys"], tiles)
    A = geom_area(feat["polys"])
    n_all = sum(counts.values())
    scale = A / (n_all * tiles.res ** 2) if n_all else 0.0
    if rules is None:
        rules, yr = parse_rules(feat.get("props", {}), ref)
    else:
        yr = feat.get("props", {}).get("target_year", "")
    coef, mapping = ref["coef"], ref["mapping"]
    pieces, water, nodata = [], 0.0, 0.0
    for idx, n in sorted(counts.items()):
        area_ha = n * tiles.res ** 2 * scale / 1e4
        if idx == 0:
            nodata += area_ha
            continue
        code = dotted(tiles.codes[idx])
        row = match_row(code, mapping)
        if row is None:
            raise ValueError(f"No mapping row for TypoCH {code}")
        p = {"typoch": code, "name": habitat_name(code, ref), "pixels": n, "area_ha": area_ha,
             "row": row["t"], "terrestrial": row["terr"]}
        if not row["terr"]:
            water += area_ha
        for v, key in (("central", "c"), ("conservative", "k")):
            g = coef[row[key]]
            p[v] = {"globio": row[key], "globio_name": g["name"], "wb": g["wb"], "pl": g["pl"], "msa": g["msa"]}
        tgt = rule_target(code, rules) if rules else None
        if tgt and row["terr"]:
            trow = match_row(tgt, mapping)
            if trow is None or not trow["terr"]:
                raise ValueError(f"Target {tgt}: open water is not terrestrial - pick a land habitat")
            p["target"] = {"typoch": tgt, "name": habitat_name(tgt, ref), "row": trow["t"]}
            for v, key in (("central", "c"), ("conservative", "k")):
                g = coef[trow[key]]
                p["target"][v] = {"globio": trow[key], "msa": g["msa"], "wb": g["wb"], "pl": g["pl"]}
        pieces.append(p)
    terr = [p for p in pieces if p["terrestrial"]]
    T_ha = sum(p["area_ha"] for p in terr)
    out = {"name": feat["name"], "area_ha": A / 1e4, "terrestrial_ha": T_ha, "water_ha": water,
           "nodata_ha": nodata, "pixels": n_all, "pixel_area_m2": tiles.res ** 2, "scale": scale,
           "geom_sha256": geom_hash(feat["polys"]), "pieces": pieces,
           "rules": [{"from": f, "to": t} for f, t in rules], "target_year": yr}
    for v in ("central", "conservative"):
        fp = sum(p["area_ha"] * (1 - p[v]["msa"]) for p in terr)
        ok = sum(p["area_ha"] * p[v]["msa"] for p in terr)
        r = {"msa": ok / T_ha if T_ha else None,
             "msa_wb": sum(p["area_ha"] * p[v]["wb"] for p in terr) / T_ha if T_ha else None,
             "msa_pl": sum(p["area_ha"] * p[v]["pl"] for p in terr) / T_ha if T_ha else None,
             "footprint_msa_ha": fp, "intact_msa_ha": ok}
        if rules:
            gain = sum(p["area_ha"] * ((p["target"][v]["msa"] if "target" in p else p[v]["msa"]) - p[v]["msa"])
                       for p in terr)
            r["gain_msa_ha"] = gain
            r["msa_target"] = (ok + gain) / T_ha if T_ha else None
            try:
                years = int(yr) - year_now if int(yr) > 1900 else int(yr)
            except (TypeError, ValueError):
                years = None
            r["years"] = years
            r["gain_msa_ha_per_year"] = gain / years if years and years > 0 else None
        out[v] = r
    return out


def fmt(x, d=2):
    """Swiss number format with apostrophe thousands, period decimals."""
    if x is None:
        return "–"
    s = f"{x:,.{d}f}".replace(",", "’")
    return s
