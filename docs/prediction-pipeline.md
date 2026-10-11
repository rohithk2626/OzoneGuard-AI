# Prediction pipeline (FUTURE)

```
DATA SOURCES ─ CAMS (Open-Meteo AQ API) · NWP forecast archive (Historical Forecast API) · solar geometry
   ↓  ml/collect_data.py          raw per-location Parquet (UTC), resumable year chunks, retry/back-off
   ↓  ml/preprocess.py            QC · hourly grid · physical limits · spatial-offset report · native-hour flag
   ↓  ml/features.py              direct multi-horizon rows (t, h, T=t+h) · leakage-safe lags · purged split
   ↓  ml/correlation.py           PAST analysis: Pearson/Spearman, heatmaps, scatter, seasonal plots
   ↓  ml/train.py                 baselines · 5 model families · per-horizon variant · UV ozone ablation
   ↓                              refit · conformal 90 % ranges · single test evaluation · SHAP/permutation
   ↓  models/                     ozone_model.joblib · uv_model.joblib · conformal.json · metadata · schema · metrics
   ↓  backend/services/prediction_service.py   live CAMS (≤ t) + live weather forecast (t+1…t+24) → same build_rows()
   ↓  GET /api/v1/predictions/24h             24 hourly rows · ranges · WHO risk · peak · high-risk windows · quality
   ↓  frontend/predictions.html               charts, table, peak, windows, quality, sources
```

## Live inference

```
lat, lon (map / GPS / typed)
  → India bounds check (400 if outside)
  → Open-Meteo AQ API (past 3 days + 2 forecast days; values after the issue hour are DISCARDED)
  → Open-Meteo Forecast API (weather for the next 24 h)
  → ml.features.build_rows(…)       ← identical code to training
  → ozone model → (UV model)         → clip ≥ 0, UV = 0 when sun < −1°
  → conformal ranges, WHO risk, peak UV, high-risk windows, anomaly (if climatology within 50 km)
  → JSON (UTC + IST timestamps)
Failure of any provider → HTTP 503 with a reason; no values are invented.
Responses are cached 10 minutes per (lat, lon rounded to 0.01°, issue hour).
```

## Spatiotemporal alignment

| Operation | METHOD | REASON | ASSUMPTION | LIMITATION |
|---|---|---|---|---|
| CAMS → point | provider nearest grid cell (~0.4°) | no interpolation artefacts; value is a real model output | point is represented by its ~45 km cell | sub-grid urban variation is lost; cell offset recorded per location (data-quality report) |
| NWP → point | provider nearest model cell (`best_match`) | same reasoning; same selection logic live and in training | model cell represents the point | different grids for CAMS and NWP (both recorded) |
| Join CAMS ↔ NWP | exact UTC timestamp join | both requested with `timezone=GMT` on the same hourly axis | provider timestamps mark the valid time | — |
| CAMS 3-hourly native | keep provider's hourly values; flag native hours (`cams_native`) | dropping 2/3 of hours would leave the live hourly forecast without training targets | provider's intermediate hours are a smooth time interpolation | test shows they are *not* plain linear (15.5 % match for O₃) → metrics also reported on native hours only |
| Lags / rolling windows | windows ending at t | leakage control | — | — |
| Weather at T | forecast valid at T | live parity | archived forecast ≈ live forecast | archived values are mostly short-lead (ADR-3) |
| Solar geometry | computed exactly at T for the requested (not grid) lat/lon | deterministic | — | — |
| Time zones | UTC internally; IST (+05:30) only in API `*_ist` fields and UI | avoid silent mixing | — | — |
| No spatial interpolation between training points | — | not needed: live inference queries the providers at the exact clicked point | — | generalisation to new points is measured by the spatial holdout |

## Reproduce

```bash
pip install -r requirements.txt
python -m ml.collect_data fetch                 # or: import-export data/raw/browser_export/ozoneguard_training_data.csv.gz
python -m ml.preprocess
python -m ml.features
python -m ml.correlation
python -m ml.train                              # ~1 h on 2 CPU cores
python -m ml.report                             # regenerates docs/ml-results.md from models/metrics.json
pytest -q
uvicorn backend.main:app --reload               # then open frontend/predictions.html
```
