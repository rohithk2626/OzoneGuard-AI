# OzoneGuard AI

OzoneGuard AI is a location-based environmental monitoring and prediction platform for India, built around **PAST → NOW → FUTURE**.

| | Page | What it shows | Status |
|---|---|---|---|
| PAST | Analytics | real daily ozone, UV and weather history for any point and period since Aug 2022, with an average day and correlations | live |
| NOW | Location | current weather, UV, NASA total-column ozone (DU), place name for any map point | live |
| FUTURE | Predictions | next-24-hour **surface ozone (µg/m³)** and **UV index**, 90 % ranges, WHO UV risk, peak UV, high-risk windows, prediction quality | **live ML models** |
| | Dashboard | now, next 24 h and last 14 days for the chosen place, plus saved locations | live |
| | Login / signup | Firebase email + password; saved locations per user | needs your Firebase project (`docs/firebase-setup.md`) |

## How the forecast works (short version)

* **Training data (real):** 38 points across all six regions of India, hourly, Aug 2022 → Oct 2026 (1.39 M location-hours). Ozone and UV "truth" from CAMS (ECMWF/Copernicus); weather from archived NWP *forecasts*; solar position computed.
* **Models:** direct multi-horizon gradient-boosted trees (one for ozone, one for UV), selected against Ridge, RandomForest, HistGB, XGBoost, LightGBM and simple baselines on a validation year; tested once on the following year and on 8 never-seen locations.
* **Live:** the API pulls the latest CAMS values and the weather forecast for the clicked point, builds features with the same code used in training, and returns 24 hourly forecasts with measured uncertainty. If a provider is down it returns an error, never an invented number.

Results: `docs/ml-results.md`. What it cannot do: `docs/scientific-limitations.md`.

## Run the website (one command)

```bash
python -m venv .venv
# Windows PowerShell:  .\.venv\Scripts\Activate.ps1      macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt
uvicorn backend.main:app --reload
```

Then open **http://127.0.0.1:8000**. The backend serves both the website (the `frontend/` folder) and the API, so nothing else needs to run.

* API docs: `http://127.0.0.1:8000/docs`
* Forecast: `http://127.0.0.1:8000/api/v1/predictions/24h?lat=17.385&lon=78.4867`
* History: `http://127.0.0.1:8000/api/v1/analytics/history?lat=17.385&lon=78.4867&start=2026-09-01&end=2026-09-30`
* Still works the old way too: serve `frontend/` separately (e.g. `python -m http.server 5500 -d frontend` or VS Code Live Server) and the pages call the API on port 8000.

Trained models are included in `models/`, so the website works without retraining. The backend loads the portable `models/*_model.json` files; the `.joblib` copies are a fallback.

A point is accepted only if it is inside India's outline (`backend/data/india_boundary.json`), so clicks in the sea or in neighbouring countries are rejected.

## Accounts and saved locations

Login, signup and saved locations use Firebase. Follow `docs/firebase-setup.md` once (about 10 minutes) and paste your project's values into `frontend/js/firebase-config.js`. Until then the site works without accounts and saved locations stay in the browser.

## Rebuild the data and models from scratch

```bash
python -m ml.collect_data fetch          # downloads from Open-Meteo (no key; ~310 requests, resumable)
#   or, to reuse the exact dataset v1:  python -m ml.collect_data import-export data/raw/browser_export/ozoneguard_training_data.csv.gz
python -m ml.preprocess                  # QC + alignment  -> docs/data-quality-report.md
python -m ml.features                    # training tables (train / val / test / spatial holdout)
python -m ml.correlation                 # PAST analysis   -> docs/correlation-analysis.md
python -m ml.train                       # benchmark + final models (~1 h on 2 CPU cores) -> models/
python -m ml.report                      # docs/ml-results.md from models/metrics.json
pytest -q
```

## Ground-truth check (CAMS against real stations)

```bash
python -m ml.validate_ground_truth csv data/external/stations/*.csv        # CSVs you downloaded (e.g. from CPCB)
python -m ml.validate_ground_truth openaq --start 2026-01-01 --end 2026-03-31   # needs OPENAQ_API_KEY in .env
```

Writes `docs/ground-truth-validation.md`. The script has not been run on real station data yet (`docs/blockers.md`).

## Environment

Copy `.env.example` to `.env`. `NASA_EARTHDATA_TOKEN` turns on the NOW page's satellite ozone and `OPENAQ_API_KEY` is only for the ground-truth check; forecasts and history need no keys. See `docs/blockers.md`.

## Documentation

| File | Contents |
|---|---|
| `docs/prediction-data-sources.md` | every dataset investigated, classified, with sources |
| `docs/architecture-decisions.md` | what changed from the original spec and why |
| `docs/prediction-pipeline.md` | pipeline, live inference, alignment table, commands |
| `docs/data-provenance.md` | where every value came from |
| `docs/data-quality-report.md` | QC results |
| `docs/data-leakage-audit.md` | feature-by-feature leakage audit |
| `docs/correlation-analysis.md` | measured correlations + figures |
| `docs/ml-results.md` | benchmark, test results, baselines, uncertainty, explainability |
| `docs/scientific-limitations.md` | honest limitations |
| `docs/blockers.md` | accounts/keys that would improve the system |
| `docs/api-documentation.md` | endpoints |
| `docs/firebase-setup.md` | accounts and saved locations: one-time Firebase setup |
| `docs/ground-truth-validation.md` | CAMS against station measurements (created when you run the check) |

Data attribution: contains modified Copernicus Atmosphere Monitoring Service information; weather data by Open-Meteo.com (CC BY 4.0).
