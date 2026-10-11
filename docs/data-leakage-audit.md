# Data leakage audit

Row definition: issue time **t** (when the forecast is made), lead **h** ∈ 1…24, target time **T = t + h**.

Rule: a feature is allowed only if its value is genuinely known at time t in live use.

## Feature-by-feature

| Feature | Definition | Historical? | AVAILABLE_AT_PREDICTION_TIME | Needs future observations? | Leakage risk / control |
|---|---|---|---|---|---|
| `lead_h` | h | yes | TRUE | no | — |
| `lat`, `lon`, `elevation_m` | location | yes | TRUE | no | — |
| `sin_doy`, `cos_doy` | day of year of T | yes | TRUE | no | calendar |
| `sin_solar_time`, `cos_solar_time` | true solar time at T | yes | TRUE | no | computed |
| `solar_elevation`, `cos_zenith`, `earth_sun_distance_au`, `daylight_hours` | NOAA solar geometry at T | yes | TRUE | no | computed, unit-tested |
| `fc_temperature_2m` … `fc_uv_index_clear_sky` | NWP **forecast** valid at T | yes (archived forecasts) | TRUE (live forecast) | no | never reanalysis/observations (ADR-3) |
| `fc_wind_dir_sin/cos` | forecast wind direction at T | yes | TRUE | no | — |
| `fc_cloud_mean_6h` | mean forecast cloud T−5…T | yes | TRUE | no | forecast only |
| `ozone_t`, `uv_t`, `no2_t`, `aod_t` | CAMS value at t | yes | TRUE | no | test: changing any CAMS value after t leaves features unchanged |
| `ozone_t_minus3`, `uv_t_minus3` | CAMS at t−3 | yes | TRUE | no | — |
| `*_mean_24h`, `*_max_24h` | rolling window t−23…t | yes | TRUE | no | window ends at t (unit-tested) |
| `*_same_hour_prev_day` | CAMS at T−24 | yes | TRUE | no | T−24 ≤ t because h ≤ 24 |
| `*_same_hour_2days` | CAMS at T−48 | yes | TRUE | no | — |
| `pred_ozone` (ablation only) | ozone-model output at T | yes | TRUE | no | produced from allowed features only |

## Removed / never used

| Candidate | AVAILABLE_AT_PREDICTION_TIME | Why excluded |
|---|---|---|
| CAMS O₃ / UV at T (or any time > t) | FALSE | the target itself / future composition |
| CAMS `uv_index_clear_sky` at T | FALSE in training form | in the archive it is analysis-like and encodes the CAMS ozone column at T; live it would be a CAMS forecast with a different error profile |
| CAMS raw forecast of O₃/UV for T | TRUE live, but no archive of 24-h-lead CAMS forecasts available | including it would create a train/serve mismatch; returned in the API only as `reference_cams_raw_forecast` |
| ERA5 / observed weather at T | FALSE | future observation (ADR-3) |
| Climatology / anomaly as feature | partly | climatology exists only at 38 points; not available for arbitrary clicks |
| Total-column ozone (OMTO3G/TROPOMI) | TRUE (daily, lagged) | not accessible for training here (blocker) |

## Split leakage

* Chronological split on issue time: train ≤ 2024-09-30 23:00 UTC, validation ≤ 2025-09-30 23:00 UTC, test after.
* **Purging:** training rows whose target time falls in validation (and validation rows whose target falls in test) are dropped (`assign_split`, unit-tested).
* **Spatial holdout:** 8 locations never enter training (also unit-tested).
* **Climatology** used for baselines and anomalies is computed from the training period only (unit-tested).
* **Model selection** uses validation only; the test year is evaluated once, after all choices were frozen.
* **Conformal calibration** uses validation residuals only.

## Tests that enforce this (`tests/test_ml_core.py`, `tests/test_predictions_api.py`)

* `test_no_future_composition_leakage`
* `test_inference_ignores_future_cams_values`
* `test_targets_never_in_feature_lists`
* `test_split_purges_boundary_rows`, `test_spatial_holdout_never_in_train`
* `test_climatology_uses_training_period_only`
* `test_horizon_count_and_lags`
