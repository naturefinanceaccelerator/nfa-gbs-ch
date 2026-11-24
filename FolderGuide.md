# _NFA_GBS – folder guide

Swiss MSA parcel tool: KML in, MSA footprint per polygon out. Same set-up as the golf project:
numbered scripts, double-click, one after the other. Raw data never in OneDrive.

## Where things are

| Where | What |
|---|---|
| here (OneDrive `05_Methodology&MRV\_NFA_GBS`) | scripts, page template, tables, brief, inputs, reports |
| `D:\NFA_data\1_sources\bafu\lebensraumkarte-schweiz` | Habitat Map v1.2 per canton (already there, reused) |
| `D:\NFA_data\1_sources\gbs` | downloaded sources with checksums, official TypoCH names (script 1) |
| `D:\NFA_data\4_projects\gbs_ch\tiles` | 2 m habitat tiles, about 600 MB (script 2) |
| `D:\NFA_data\4_projects\gbs_ch\web` | the platform, ready to publish (script 5) |
| `D:\NFA_data\4_projects\gbs_ch\github.git`, `site.git` | Git folders (script 6) |
| GitHub `naturefinanceaccelerator/nfa-gbs-ch` | code (`main`) plus platform (`gh-pages`), public |

## Folders here

- `00_Brief` – project start brief
- `01_Input` – drop KML / KMZ / GeoJSON here for batch reports (never uploaded to GitHub)
- `03_Validation` – tile method versus exact overlay
- `04_Output` – one dated folder per input file: `report.docx`, `results.csv`, `habitats.csv`, `result.json`, `map.html` (never uploaded)
- `page` – platform template, Leaflet, proj4, sample parcels
- `ref` – the two tables that carry the method: GLOBIO coefficients, TypoCH → GLOBIO mapping

## Run order

1. `0_run_all.py` – runs 1 to 5. First time 1–3 h (tiles), later minutes.
2. Test: `start_local.bat` in `D:\NFA_data\4_projects\gbs_ch\web`.
3. `6_gbs_github.py` – publishes. Platform: https://naturefinanceaccelerator.github.io/nfa-gbs-ch/

Only new parcels: drop the KML into `01_Input`, double-click `4_gbs_report.py`.

## Polygon attributes (optional)

KML ExtendedData, GeoJSON properties, or a CSV with the same file name and a column `name`:
`target_habitat` (TypoCH code, e.g. 4.2.4), `target_from` (e.g. 4.5 or 4.5;8.2), `target_year` (e.g. 2035).

## Rules

- Results are labelled "GBS-consistent MSA (GLOBIO4 land-use module)", never "GBS".
- Change the method only in `ref\*.csv`, then rerun 3, 5, 6. The web page and the scripts read the same tables.
- Final reports go to SharePoint 07 the same week.
