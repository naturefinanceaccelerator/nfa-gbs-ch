# Swiss MSA Parcel Tool

Biodiversity footprint per parcel in Switzerland, as a **GBS-consistent MSA (GLOBIO4 land-use module)**.
Upload a KML, get MSA, MSA.ha footprint and the gain of a measure for every polygon, with every number behind it.

**Platform:** https://naturefinanceaccelerator.github.io/nfa-gbs-ch/
Files stay in the browser of the user. Nothing is uploaded to a server.

Built by NFA Foundation (Nature Finance Accelerator). Contact: matthias.haeni@nfa.ch

## Method

1. Polygon (WGS84) → Swiss LV95 (EPSG:2056).
2. Habitat Map of Switzerland v1.2 (FOEN/WSL) → TypoCH habitat type per 2 m pixel. A pixel counts when its centre lies inside the polygon.
3. Habitat area = polygon area × pixel share.
4. TypoCH → GLOBIO land-use class: `ref/typoch_globio_mapping.csv` (longest matching code).
5. GLOBIO class → MSA birds & mammals, MSA plants: `ref/globio_msa_coefficients.csv` (GLOBIOweb technical documentation, PBL 2023, Table 3.1).
   MSA overall = mean of both groups (GLOBIO4 code, `CalcLanduseMSA`).
6. Open water is outside the terrestrial MSA.

```
Footprint MSA.ha = Σ area_i × (1 − MSA_i)
Gain MSA.ha      = Σ area_i × (MSA_i,target − MSA_i)
```

Two variants, always both reported: **central** (GLOBIO4 classes) and **conservative** (managed forest 0.70 and sealed surfaces 0.05 from GLOBIO 3.5; mown semi-natural grassland as extensive rangeland; arable land as intensive cropland).

Not included: road and rail disturbance, fragmentation, nitrogen deposition, climate change. Not the official Global Biodiversity Score (GBS) of CDC Biodiversité, which uses an adapted GLOBIO 3.6.

## Validation

`3_gbs_check.py` compares the 2 m tiles with an exact intersection of the original Habitat Map polygons (squares of 1 and 10 ha, 15 m strips, the input parcels). Result: `03_Validation/validation_summary.json`, also shown on the platform.

## Files

| File | Role |
|---|---|
| `gbs_core.py` | the engine (same arithmetic as the JavaScript in `page/gbs_template.html`) |
| `1_gbs_sources.py` | downloads the sources with checksums (GLOBIO4 code, documentation, TypoCH lookup) |
| `2_gbs_tiles.py` | Habitat Map → 2 m habitat tiles |
| `3_gbs_check.py` | validation against an exact overlay |
| `4_gbs_report.py` | batch reports: Word, CSV, JSON, map |
| `5_gbs_web.py` | builds the platform |
| `6_gbs_github.py` | publishes code (branch `main`) and platform (branch `gh-pages`) |
| `ref/` | coefficient and mapping tables |
| `page/` | platform template, Leaflet, proj4, sample parcels |

## Sources

- PBL (2023): Technical documentation of the GLOBIOweb datasets. https://www.globio.info
- GLOBIO4 model code: https://github.com/GLOBIO4/GlobioModelPublic
- Schipper A. M. et al. (2020): Projecting terrestrial biodiversity intactness with GLOBIO 4. Global Change Biology 26: 760–771. https://doi.org/10.1111/gcb.14848
- PBL (2016): The GLOBIO model. A technical description of version 3.5.
- Price B. et al. (2025): The Habitat Map of Switzerland v1_2 2025. EnviDat. https://www.doi.org/10.16904/envidat.723 · Source: FOEN/WSL
- Delarze R., Gonseth Y., Eggenberg S., Vust M. (2015): Lebensräume der Schweiz. hep, Bern.
- Leaflet (BSD-2-Clause) and proj4js (MIT): `page/lib`
