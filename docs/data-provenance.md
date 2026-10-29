# Data provenance

Every training value can be traced back to one API request.

## Chain of custody

| Stage | File | Produced by | What changes |
|---|---|---|---|
| 0. API responses | (browser memory) | Open-Meteo Air Quality API + Historical Forecast API, requested 7 Oct 2026 | — |
| 1. Export | `data/raw/browser_export/ozoneguard_training_data.csv.gz` | browser export; SHA-256 `3f7230eb94ad9e3f1efe6c7cf2040c18a05d26e96478ccee89d7666006d6ed15`, 1,389,888 rows | values copied verbatim, no rounding |
| 2. Raw per location | `data/raw/openmeteo/<location>.parquet` | `python -m ml.collect_data import-export …` (or `fetch`) | parsed to typed columns; timestamps → UTC-aware |
| 3. Clean | `data/intermediate/cleaned.parquet` + `quality_report.json` | `python -m ml.preprocess` | duplicates removed, hourly grid completed, values outside physical limits → NaN, `solar_elevation` and `cams_native` added |
| 4. Model tables | `data/processed/{train,val,test,spatial_holdout}.parquet` | `python -m ml.features` | direct multi-horizon rows (issue time, lead, features, targets, split) |
| 5. Artifacts | `models/xgboost/*`, `models/lstm/*` | `python -m ml.train_xgboost`, `python -m ml.train_lstm` | trained models, conformal tables, metrics, climatology |

## Request definitions (exactly what was requested)

* **CAMS** — `https://air-quality-api.open-meteo.com/v1/air-quality?latitude=<lat>&longitude=<lon>&hourly=ozone,uv_index,uv_index_clear_sky,nitrogen_dioxide,aerosol_optical_depth&start_date=<s>&end_date=<e>&timezone=GMT&domains=cams_global`
* **NWP forecast archive** — `https://historical-forecast-api.open-meteo.com/v1/forecast?latitude=<lat>&longitude=<lon>&hourly=temperature_2m,relative_humidity_2m,dew_point_2m,surface_pressure,cloud_cover,precipitation,shortwave_radiation,wind_speed_10m,wind_direction_10m,uv_index,uv_index_clear_sky&start_date=<s>&end_date=<e>&timezone=GMT`
* Chunks (per location): 2022-08-04→2023-07-31, 2023-08-01→2024-07-31, 2024-08-01→2025-07-31, 2025-08-01→2026-10-05.

## Column provenance

| Column | Source / dataset | Original variable | Unit | Transform | QC |
|---|---|---|---|---|---|
| `cams_ozone` | CAMS global (ECMWF) via Open-Meteo | `ozone` (surface) | µg/m³ | none | NaN if < 0 or > 600 |
| `cams_uv_index` | CAMS via Open-Meteo | `uv_index` (all-sky) | — | none | NaN if outside 0–25 |
| `cams_uv_index_clear_sky` | CAMS via Open-Meteo | `uv_index_clear_sky` | — | none (stored, not a feature) | 0–25 |
| `cams_nitrogen_dioxide` | CAMS via Open-Meteo | `nitrogen_dioxide` | µg/m³ | none | 0–1000 |
| `cams_aerosol_optical_depth` | CAMS via Open-Meteo | `aerosol_optical_depth` (550 nm) | — | none | 0–10 |
| `wx_*` | Open-Meteo Historical Forecast API, `best_match` | same name without prefix | °C, %, hPa, mm, W/m², km/h, ° | none | physical limits in `ml/config.py` |
| `aq_lat/aq_lon`, `wx_lat/wx_lon`, `wx_elev` | API response metadata | `latitude`, `longitude`, `elevation` | °, m | none | used for the alignment report |
| `time_utc` | API (`timezone=GMT`) | `time` | ISO-8601 | parsed as UTC | hourly grid check |
| `solar_elevation`, `cos_zenith`, … | computed (`ml/solar.py`, NOAA equations) | — | ° | — | unit-tested |

## Attribution required (CC BY 4.0)

"Contains modified Copernicus Atmosphere Monitoring Service information [2022–2026]. Weather data by Open-Meteo.com." — shown on the Predictions page.

## Version identifiers

* Dataset version: `og-cams-ifs-2022.08-2026.10-v1` (`ml/config.py`)
* Model version: `1.0.0` (`models/xgboost/model_metadata.json`)
