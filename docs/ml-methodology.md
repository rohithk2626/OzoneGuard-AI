# ML Methodology

Two direct multi-horizon models forecast the next 24 hours:

* **Model A — surface ozone (µg/m³)**, target = CAMS surface ozone.
* **Model B — UV index**, target = CAMS all-sky UV index. Predicted ozone is fed to it only if a validation ablation shows ≥ 1 % MAE gain.
* **UV risk** is derived from the continuous UV forecast on the WHO scale (no separate classifier).

Each row = (location, issue time t, lead h = 1…24). Features: lead time, location, solar geometry and calendar at T = t + h, the NWP weather forecast valid at T, and CAMS values up to t (latest, t−3, same hour 1 and 2 days earlier, 24-h mean/max). Families benchmarked: Ridge, RandomForest, HistGradientBoosting, XGBoost, LightGBM, against persistence / same-hour-previous-day / climatology / raw-NWP-UV baselines. Chronological train/validation/test split with purging; 8 locations held out entirely. 90 % split-conformal ranges.

Details: `architecture-decisions.md`, `prediction-pipeline.md`, `data-leakage-audit.md`, `ml-results.md`, `scientific-limitations.md`.
