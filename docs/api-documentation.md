# API Documentation

The backend is versioned under `/api/v1`. Interactive docs: `http://127.0.0.1:8000/docs`.

| Method | Path | Purpose | Time frame |
|---|---|---|---|
| GET | `/api/v1/health` | service health | — |
| GET | `/api/v1/location/validate?lat=&lon=` | is the point inside India's outline? | — |
| GET | `/api/v1/location/presets` | the 38 named model locations (quick picks) | — |
| GET | `/api/v1/location/overview?lat=&lon=` | current weather, UV, NASA total-column ozone, place name | NOW |
| GET | `/api/v1/ozone/current?lat=&lon=` | NASA OMTO3G total-column ozone (DU) | NOW |
| GET | `/api/v1/predictions/24h?lat=&lon=&model=` | 24-hour surface-ozone + UV forecast | FUTURE |
| GET | `/api/v1/predictions/model-info?model=` | model metadata and headline metrics | FUTURE |
| GET | `/api/v1/predictions/models` | both model families: availability, default, test metrics | FUTURE |
| GET | `/api/v1/analytics/history?lat=&lon=&start=&end=` | real daily ozone / UV / weather history | PAST |
| GET | `/api/v1/analytics/limits` | earliest day, today (IST), longest range | PAST |

## `GET /api/v1/predictions/24h`

**Inputs:** `lat` (−90…90), `lon` (−180…180); must be inside India's outline (`backend/data/india_boundary.json`; sea and neighbouring countries are rejected). Optional `model` = `xgboost` | `lstm`; when omitted the server default is used (`OZONEGUARD_MODEL` in `.env`, otherwise `xgboost`).

**Responses**

* `200` — forecast (schema `PredictionResponse`, `backend/schemas/predictions.py`)
* `400` — outside India
* `422` — not a valid number, or `model` is not `xgboost` / `lstm`
* `503` — `{"detail": {"status": "provider_unavailable" | "model_not_trained" | "unavailable", "message": "…"}}`. No values are invented.

**Main fields**

| Field | Meaning |
|---|---|
| `issue_time_utc` / `issue_time_ist` | hour the forecast is made from |
| `predictions[24]` | `lead_hours`, `time_utc`, `time_ist`, `ozone{value, lower, upper, anomaly}`, `uv{value, lower, upper, risk, risk_level}`, `solar_elevation_deg`, `weather{…}` |
| `peak_uv` | highest forecast UV, its time, range and WHO risk |
| `high_risk_windows` | contiguous hours with forecast UV ≥ 6 (rounded) |
| `possible_high_risk_windows_upper_bound` | same, using the upper end of the 90 % range |
| `targets` | what each number represents (units, truth source) |
| `uncertainty` | method and meaning of the ranges |
| `prediction_quality` | `tier` (high / medium / low), distance to nearest training point, measured errors |
| `model` | `name` (`xgboost` / `lstm`), version, algorithms, whether UV uses predicted ozone |
| `data_status` | live sources, notes, anomaly availability |
| `reference_cams_raw_forecast` | CAMS' own raw forecast for the same hours (reference only; not evaluated) |

Example: `curl "http://127.0.0.1:8000/api/v1/predictions/24h?lat=17.385&lon=78.4867"`

## `GET /api/v1/analytics/history`

**Inputs:** `lat`, `lon` (inside India); `start`, `end` as `YYYY-MM-DD` Indian days. Defaults: `end` = today (IST), `start` = 29 days earlier. At most 366 days; not before 2022-08-04; not in the future.

**Responses**

* `200` — history (fields below)
* `400` — outside India, or an unusable date range (the message says which)
* `422` — not a valid number or date
* `503` — `{"detail": {"status": "provider_unavailable" | "no_data", "message": "…"}}`. No values are invented.

| Field | Meaning |
|---|---|
| `daily[]` | one row per Indian day: `date`, `hours`, `partial`, `ozone_mean`, `ozone_max`, `uv_max`, `uv_risk`, `no2_mean`, `aod_mean`, `temp_mean/min/max`, `humidity_mean`, `cloud_mean`, `precip_sum`, `wind_mean`, `sunlight_mean` |
| `average_day[24]` | mean ozone, UV and temperature for each hour of the day (IST) over the period |
| `summary` | period means, hourly ozone range, highest UV day, number of days in each WHO UV category |
| `relationships` | Pearson correlations in daylight hours (ozone–UV, ozone–temperature, ozone–humidity, ozone–sunlight, UV–cloud) with sample sizes |
| `units`, `data_status` | units of every value, sources and their status |

A day with fewer than 20 hours of data (normally today) is marked `partial` and is left out of `summary` averages. Hours that have not happened yet are never returned. Sources: CAMS via the Open-Meteo Air Quality API (ozone, UV, NO₂, haze) and the Open-Meteo Historical Forecast API (weather), the same two sources as the training data.

## Accounts

There are no account endpoints. Login, signup and saved locations are handled in the browser by Firebase (`frontend/js/account.js`, `docs/firebase-setup.md`).
