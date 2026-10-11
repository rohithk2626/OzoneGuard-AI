# Architecture decisions (prediction system)

The product concept is unchanged: **PAST (Analytics) → NOW (Location) → FUTURE (Predictions)**. These records cover *how* the FUTURE side is built where it departs from the original specification (OG.docx).

---

## ADR-1 — Ozone forecast target: surface ozone, not total-column ozone

1. **Original approach:** forecast "ozone" hourly in Dobson Units from NASA OMTO3G (e.g. "10:00 → 280 DU, 11:00 → 283 DU").
2. **Problem:** OMTO3G is *total-column* ozone (mostly stratospheric). It is measured once per day per location (one satellite overpass), so an hour-by-hour DU forecast has no hourly truth to learn from. It also says nothing direct about the ground-level exposure the product is about. Training needs an Earthdata token we do not have here.
3. **Alternatives investigated:** OMTO3G, TROPOMI total column, ERA5 `tco3`, MERRA-2 TO3, CAMS EAC4, CAMS surface O₃, CPCB/OpenAQ station O₃.
4. **Evidence:** CAMS surface O₃ is hourly, gap-free (0.01 % missing after QC), covers all of India and was reachable. CPCB is the true ground observation but has no scriptable access from here (OpenAQ needs a key).
5. **Final choice:** Model A forecasts **surface ozone (µg/m³)** using CAMS as truth. Total-column ozone stays a separate NOW-page product (OMTO3G, DU).
6. **Impact:** the Predictions page labels ozone as "ground-level ozone, µg/m³"; the Location page keeps "total-column ozone, DU". The two are never mixed.

## ADR-2 — UV target: CAMS all-sky UV index

1. **Original:** "UV from Open-Meteo".
2. **Problem:** the Open-Meteo *weather* UV index is itself a forecast; using it as truth would teach the model to copy another forecast. No public ground UV network for India was found (IMD data not public).
3. **Alternatives:** OMI OMUVBd (noon only, 1°), TEMIS (clear-sky noon), ERA5 `uvb` (radiation, not UV index), CAMS UV index.
4. **Evidence:** CAMS UV is hourly, all-sky, includes ozone/aerosol/cloud effects; r = 0.88 with cos(solar zenith) (data-quality report) — physically consistent; 0.2 % of night hours > 0.05.
5. **Choice:** Model B forecasts **CAMS UV index**; the NWP UV index is used only as an input feature.
6. **Impact:** "truth" is model-derived. Documented in scientific-limitations.md.

## ADR-3 — Training weather = archived *forecasts*, not reanalysis/observations

1. **Original:** historical weather from Open-Meteo, no distinction made.
2. **Problem:** at inference only a weather forecast exists. Training on ERA5 ("perfect" weather) makes the model trust weather inputs more than it should.
3. **Alternatives:** ERA5 / ERA5-Land, Historical Forecast API, Previous Runs API.
4. **Evidence/reasoning:** the Historical Forecast API stores the operational forecasts actually issued (`best_match`, the same selection the live Forecast API uses). Previous Runs gives fixed 24-h leads but only from Jan 2024 (too short with our 2-year train window).
5. **Choice:** Historical Forecast API for training, Forecast API live.
6. **Impact:** remaining mismatch: archived values are mostly short-lead (0–24 h) forecasts; live 24-h-lead weather is slightly worse → listed in limitations; Previous Runs is the v2 fix.

## ADR-4 — Direct multi-horizon forecasting, one model per target

1. **Original:** not specified ("next 1 … 24 hours").
2. **Problem:** recursive forecasting compounds its own errors and would need future CAMS inputs.
3. **Alternatives:** recursive; one model per horizon (24 models); a single direct model with lead time as a feature; seq2seq (LSTM/GRU/TFT).
4. **Evidence:** per-horizon vs single-model benchmark in ml-results.md. Sequence models were not trained: 2 CPU cores, tabular inputs with a strong deterministic structure (solar geometry), and gradient-boosted trees are the standard strong baseline for this; a neural benchmark is listed as future work rather than claimed.
5. **Choice:** single direct model per target with `lead_h` as a feature (simpler deployment, shares data across leads), unless the per-horizon variant is clearly better (it was not — see results).
6. **Impact:** inference = one batch of 24 rows per target.

## ADR-5 — Model family chosen by validation, not by reputation

Benchmarked Ridge, RandomForest, HistGradientBoosting, XGBoost, LightGBM against persistence, same-hour-previous-day and climatology baselines (plus raw NWP UV for UV). Rule: lowest validation MAE; take a simpler family if within 1 %. Test set used once. Results: ml-results.md.

## ADR-6 — Ozone in the UV model only if it helps

The spec wanted predicted ozone to feed the UV model. We ran an ablation (no ozone / observed surface-ozone lags / predicted surface ozone). Rule: keep an ozone input only if validation MAE improves ≥ 1 %. Physically, UV is controlled by the *column* ozone, not surface ozone, so no large gain was expected; the outcome is reported as measured in ml-results.md.

## ADR-7 — Ozone anomaly = standardized anomaly vs train-period climatology

* Climatology per location × calendar month × UTC hour: mean μ and standard deviation σ, **training period only** (Aug 2022 – Sep 2024) to avoid leakage.
* `anomaly = O3 − μ` (µg/m³) and `z = (O3 − μ) / σ`.
* z-score chosen over percent anomaly because ozone at night can be near zero (percent blows up) and σ varies strongly by hour.
* Available only within 50 km of one of the 38 sampled points (climatology does not exist elsewhere); otherwise the API returns `null` with a reason.
* The models predict raw concentration (not the anomaly) because a climatology does not exist for arbitrary map clicks.

## ADR-8 — Uncertainty: split-conformal (Mondrian) intervals

Absolute residuals on the validation year, grouped by lead bucket (1–3, 4–6, 7–12, 13–24 h) × predicted-value bin; the ⌈(n+1)(0.9)⌉-th residual gives a 90 % range. Compared with LightGBM quantile regression on the test year (coverage/width in ml-results.md). Displayed as "90 % range", never as "confidence".

## ADR-9 — Prediction quality for arbitrary coordinates

8 locations were held out entirely. Tiers by distance to the nearest training point: high ≤ 50 km, medium ≤ 350 km (range covered by the holdout evaluation, 150–300 km), low > 350 km (accuracy NOT VERIFIED). Each tier is shown with the measured error that applies to it.

## ADR-10 — Data transport during the build

The build sandbox could not reach Open-Meteo. The identical API requests were run from the user's browser, saved as one gzip CSV (SHA-256 recorded) and imported with `ml.collect_data import-export`. `ml.collect_data fetch` reproduces the same files directly on any machine with internet.
