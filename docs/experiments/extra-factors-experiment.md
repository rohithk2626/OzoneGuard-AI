# Experiment: boundary layer height and distance to the sea (27 Oct 2026)

**Question.** Would two missing categories of factors improve the forecasts?

* **Air mixing**: boundary layer height (BLH), the depth of the air layer mixed by the ground. Used at the target hour and 6 hours earlier.
* **Land type**: distance from the city to the open sea (`coast_km`).

**Answer.** Not enough to change the live models. Both were tested and recorded; neither was added to the production pipeline.

## Data

| Factor | Source | Notes |
|---|---|---|
| `wx_boundary_layer_height` (m) | Open-Meteo Historical Forecast API, `best_match`, same coordinates and `timezone=GMT` as the training export | **Archived only from 1 Sep 2024.** Before that every value is empty, for every model tried (best_match, ECMWF IFS, GFS, ICON, JMA, GEM). File: `Downloads\ozoneguard_boundary_layer_height.csv` (1,389,888 rows, 18,359 non-empty hours per city, no gaps after Sep 2024). |
| `coast_km` | Computed with the `global-land-mask` 1 km land/sea mask; lakes not connected to the ocean are ignored | `docs/experiments/coast_km.json`. E.g. Kochi 3.5, Mumbai 8.4, Delhi 868, Leh 1,421 km. |

Because BLH does not exist for the production training period (Aug 2022 to Sep 2024), it cannot simply be added to the current models.

## Method

* Every variant is trained on the **same 400,000 rows** (issue times Oct 2024 to Sep 2025, the period with BLH), using the **production XGBoost settings** (700 trees, depth 8, learning rate 0.05).
* Each is scored on the **production test year** (Oct 2025 to Oct 2026): 1,064,400 rows for the 30 training cities, and 283,840 rows for the 8 cities never used in training.
* Ozone was repeated with 3 random seeds and averaged. The seed-to-seed spread was 0.01 to 0.02 (known cities) and 0.03 to 0.06 (unseen cities).

Variants: **A** current factors; **B** + BLH; **C** + coast distance; **D** + both.

## Results: ozone (mean absolute error, µg/m³; 3-seed average)

| Variant | 30 known cities | 8 unseen cities | Known, night | Unseen, night |
|---|---|---|---|---|
| A current factors | 10.47 | 11.27 | 10.55 | 11.83 |
| B + boundary layer | 10.38 (−0.9 %) | 11.37 (**+0.9 %**) | 10.42 (−1.2 %) | 12.12 (**+2.4 %**) |
| C + coast distance | 10.47 (0.0 %) | 11.19 (−0.7 %) | 10.55 (0.0 %) | 11.73 (−0.9 %) |
| D + both | 10.35 (−1.2 %) | 11.22 (−0.4 %) | 10.39 (−1.4 %) | 11.92 (+0.8 %) |

## Results: UV index (mean absolute error)

All four variants: 0.201 (known cities) and 0.211 to 0.212 (unseen cities). The new factors made no difference, as expected: mixing depth affects pollutants, not sunlight.

## Interpretation

* **Boundary layer height helps a little where the model has seen the city before**, mostly at night (−1.2 %), which matches the physics: shallow night-time layers trap air near the ground. But it **makes unseen cities slightly worse**, especially at night (+2.4 %). The model learns city-specific mixing patterns that do not carry over to new places. Since the website accepts any point in India, the unseen-city result matters most.
* **Coast distance** has no effect on known cities and a small benefit (−0.7 %) on unseen ones, comparable to the seed spread.
* **Both together** give −1.2 % on known cities and −0.4 % on unseen ones.
* The project's own rule for adding an input (`ml/train_xgboost.py`, UV ablation: keep only if the error improves by at least 1 %) is not met on the unseen cities by any variant.

## Decision

Production models unchanged. Adding BLH would also mean training only on data from Sep 2024 onward, and fetching one more live variable. Adding coast distance would need the land mask at run time for arbitrary map clicks. Neither cost is justified by a gain of under 1 %.

**Revisit BLH** when more archived years exist, or if training moves to real station data, where local mixing may matter more than it does for the 45 km CAMS grid.

## Side finding

Variant A, trained only on **one recent year** (Oct 2024 to Sep 2025, 400 k rows), scored **10.47** on the test year. The production model, trained on Aug 2022 to Sep 2024 (2.27 M rows), scores **10.57**. Recent data appears to matter more than older data, probably because CAMS itself is upgraded over time. Refitting the final models on train + validation (Aug 2022 to Sep 2025) before deployment is a likely, cheap improvement worth testing.

## Re-running

Needs `pip install global-land-mask` (scipy is already installed with scikit-learn) and the rebuilt training tables (`ml.collect_data import-export`, `ml.preprocess`, `ml.features`).

```bash
python -m ml.experiments.coast_distance
python -m ml.experiments.extra_factors <path to ozoneguard_boundary_layer_height.csv>
```

Results are written to `docs/experiments/experiment_results.json`.
