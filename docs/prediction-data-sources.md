# Prediction data sources — investigation and selection

Research date: 7 Oct 2026. Facts come from the providers' own pages (links at the bottom). **NOT VERIFIED** marks anything we could not confirm on an official page.

Classification key: **RECOMMENDED** (used), **POSSIBLE** (good, but blocked or not needed for v1), **NOT RECOMMENDED** (usable but a worse fit), **REJECTED** (unsuitable for this task).

## 1. Comparison table

| Dataset | Provider / version | Variables (units) | Spatial res. | Temporal res. | Coverage | India | Access / auth | Licence | Class |
|---|---|---|---|---|---|---|---|---|---|
| **CAMS global composition forecasts via Open-Meteo Air Quality API** | ECMWF CAMS, domain `cams_global` | surface O₃ (µg/m³), UV index, clear-sky UV index, NO₂ (µg/m³), AOD 550 nm | ~0.4° (~45 km) | 3-hourly native, served hourly | **4 Aug 2022 →** present + 5-day forecast | Yes | REST, no key (free tier: 600/min, 5,000/h, 10,000/day) | CC BY 4.0 (credit CAMS + Open-Meteo) | **RECOMMENDED** — target truth + recent composition inputs |
| **Open-Meteo Historical Forecast API** (`best_match`) | Open-Meteo archive of operational NWP runs | T2m, RH, dew point, pressure, cloud, precip, shortwave, wind, NWP UV index | model-dependent (~0.1–0.25° over India) | hourly | ~2022 → present (model-dependent; IFS 2017, GFS 2021) | Yes | REST, no key | CC BY 4.0 | **RECOMMENDED** — weather features in training (forecasts, not observations) |
| **Open-Meteo Forecast API** (`best_match`) | Live NWP forecasts | same as above | same | hourly | live, 16 days ahead | Yes | REST, no key | CC BY 4.0 | **RECOMMENDED** — weather features at live inference (same model family as training) |
| Open-Meteo Previous Runs API | Fixed-lead archived forecasts (`_previous_day1..7`) | weather | per model | hourly | most models from Jan 2024 | Yes | REST | CC BY 4.0 | **POSSIBLE** — would give exact 24-h-lead weather in training; shorter history (v2 improvement) |
| Open-Meteo Historical Weather API (ERA5 / ERA5-Land) | ECMWF reanalysis | weather | 0.25° / 0.1° | hourly | 1940 / 1950 → ~5-day lag | Yes | REST | CC BY 4.0 | **NOT RECOMMENDED** for training features: reanalysis = "perfect" weather, but at inference only a forecast exists → train/inference mismatch |
| NASA OMI/Aura **OMTO3G v004** | NASA GES DISC | Total-column O₃ (DU), QA flags | 0.25° | daily (one overpass ~13:45 local) | Oct 2004 → present | Yes | HTTPS, **Earthdata Login token** | Open (EOSDIS) | **POSSIBLE** — kept for the NOW page; blocked for training here (no token); daily cadence; OMI row anomaly; Aura end of science ops expected ≤ 2028 |
| Sentinel-5P TROPOMI L2 O₃ total column | ESA / Copernicus (also GES DISC `S5P_L2__O3_TOT_HiR` v2) | total O₃ column (mol/m²) | 3.5 × 5.5 km | per orbit, ~daily | Apr 2018 → present | Yes | CDSE account / Earthdata Login | Copernicus free & open | **POSSIBLE** — best successor to OMI for total column; needs account; L2 swath regridding |
| NASA OMI **OMUVBd** v003 | NASA GES DISC | UV index & erythemal dose at local solar noon | 1° | daily (noon only) | Oct 2004 → | Yes | Earthdata Login | Open | **NOT RECOMMENDED** — one noon value per day at 1° cannot supervise an hourly 24-h UV forecast |
| ERA5 single levels (CDS) | ECMWF | `tco3` total-column ozone (kg/m²), `uvb` surface downward UV (J/m², accumulated) | 0.25° | hourly | 1940 → | Yes | CDS API key + licence acceptance | CC BY 4.0 | **POSSIBLE** — strong for a historical total-ozone feature; blocked (account); `uvb` is radiation, not UV index (unit questions on ECMWF forum) |
| MERRA-2 (`M2T1NXSLV`, TO3) | NASA GMAO | total ozone (DU) | 0.5° × 0.625° | hourly | 1980 → (~3-week lag) | Yes | Earthdata Login | Open | **POSSIBLE** — alternative total-ozone history; lag makes it unusable live |
| CAMS global reanalysis **EAC4** (ADS) | ECMWF CAMS | O₃ (surface + total column), AOD | **0.75°** | 3-hourly | 2003 → (4–6-month lag) | Yes | ADS key + licence | CC BY 4.0 | **POSSIBLE** — longer history than Open-Meteo but coarser, lagged, no UV index; needs account |
| CAMS global forecasts (ADS, raw GRIB) | ECMWF CAMS | as Open-Meteo + total column O₃ | 0.4° | 1–3-hourly | 2015 → | Yes | ADS key + licence | CC BY 4.0 | **POSSIBLE** — needed to benchmark against CAMS' own 24-h-lead forecast (archived runs); blocked (account) |
| CPCB CAAQMS stations | Central Pollution Control Board | O₃ (µg/m³) + other pollutants | point stations | 15-min / hourly | NOT VERIFIED | India only | CCR portal download (captcha/manual); data.gov.in "API does not exist, request API" | GODL-India (data.gov.in); CCR terms NOT VERIFIED | **POSSIBLE** — the true ground observation; no scriptable access found from here → validation of CAMS is future work |
| OpenAQ v3 | OpenAQ (aggregates gov. networks) | O₃ and others | stations | varies | varies | Yes (CPCB inclusion NOT VERIFIED) | **API key required** (`X-API-Key`), 60/min | per-provider licence | **POSSIBLE** — blocked (needs key); best scriptable route to CPCB-type data |
| TEMIS (KNMI) UV index / ozone | KNMI / ESA | clear-sky UV index at solar noon, assimilated ozone | 0.25° | daily (noon) | 2002 → | Yes (+12 Indian station files) | web files | NOT VERIFIED | **NOT RECOMMENDED** — clear-sky, noon-only; cloud-modified version mainly Europe/Africa |
| IMD UV observations | India Meteorological Department | — | — | — | — | — | No public dataset/API found (Data Service Portal on request) | NOT VERIFIED | **REJECTED** for v1 — not publicly accessible |
| Open-Meteo UV index from the weather API (NWP) | Open-Meteo/NWP | UV index | model | hourly | as above | Yes | REST | CC BY 4.0 | **RECOMMENDED as a feature**, **REJECTED as the target** — it is itself a forecast; using it as truth would make the model learn one forecast from another |

## 2. What we actually use

| Role | Source | Why |
|---|---|---|
| Ozone target (truth) | CAMS surface O₃ (µg/m³) | The product is about ground-level/public exposure. It is the only scriptable, gap-free, hourly, India-wide surface-ozone series we could reach. |
| UV target (truth) | CAMS all-sky UV index | Hourly, includes ozone column, aerosol and cloud effects, India-wide. No public ground UV network exists for India. |
| Inputs up to issue time | CAMS O₃, UV, NO₂, AOD | Same source as the targets → no unit or definition mismatch for lags. |
| Weather inputs for the next 24 h | Historical Forecast API (training) / Forecast API (live) | At inference only a **forecast** exists, so training uses archived **forecasts** too. |
| Solar inputs | NOAA solar-position equations | Exact for any future hour; no data access needed. |
| Total-column ozone (NOW page) | NASA OMTO3G (existing service) | Displayed separately in DU; not mixed with surface ozone. |

## 3. Data actually downloaded (dataset v1)

* 38 points (30 training + 8 spatial-holdout) across North, South, East, West, Central and Northeast India.
* 4 Aug 2022 00:00 UTC → 5 Oct 2026 23:00 UTC, hourly: **1,389,888 location-hours**, 21 variables.
* Retrieved 7 Oct 2026 with 310 API requests. SHA-256 of the export: `3f7230eb94ad9e3f1efe6c7cf2040c18a05d26e96478ccee89d7666006d6ed15`.

## Sources

* Open-Meteo: [Air Quality API](https://open-meteo.com/en/docs/air-quality-api), [Historical Forecast API](https://open-meteo.com/en/docs/historical-forecast-api), [Historical Weather API](https://open-meteo.com/en/docs/historical-weather-api), [Previous Runs API](https://open-meteo.com/en/docs/previous-runs-api), [Terms](https://open-meteo.com/en/terms), [Pricing / limits](https://open-meteo.com/en/pricing)
* NASA: [OMTO3G v004](https://www.earthdata.nasa.gov/data/catalog/ges-disc-omto3g-004), [OMUVBd v003](https://catalog-beta.data.gov/dataset/omi-aura-surface-uvb-irradiance-and-erythemal-dose-daily-l3-global-gridded-1-0-degree-x-1-), [MERRA-2 M2T1NXSLV](https://www.earthdata.nasa.gov/data/catalog/ges-disc-m2t1nxslv-5.12.4), [Aura status](https://en.wikipedia.org/wiki/Aura_(satellite))
* ESA: [S5P L2 ozone](https://sentinels.copernicus.eu/data-products/-/asset_publisher/fp37fc19FN8F/content/sentinel-5-precursor-level-2-ozone), [CDSE Sentinel-5P](https://documentation.dataspace.copernicus.eu/Data/SentinelMissions/Sentinel5P.html)
* ECMWF: [ERA5 single levels](https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels?tab=overview), [CAMS EAC4](https://ads.atmosphere.copernicus.eu/datasets/cams-global-reanalysis-eac4?tab=overview), [CAMS global forecasts](https://ads.atmosphere.copernicus.eu/datasets/cams-global-atmospheric-composition-forecasts?tab=overview), [ECMWF forum: ERA5 uvb units](https://forum.ecmwf.int/t/is-the-uvb-parameter-in-era5-monthly-data-actually-stored-in-millijoules-mj-m-despite-being-documented-as-j-m/13890)
* OpenAQ: [API key](https://docs.openaq.org/using-the-api/api-key), [rate limits](https://docs.openaq.org/using-the-api/rate-limits)
* CPCB: [data.gov.in AQI resource](https://data.gov.in/resource/real-time-air-quality-index-various-locations)
* TEMIS: [UV index](https://www.temis.nl/uvradiation/UVindex.php)
* WHO: [Global Solar UV Index: A Practical Guide (2002)](https://www.who.int/publications/i/item/9241590076)
