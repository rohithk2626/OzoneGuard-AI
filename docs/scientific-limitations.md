# Scientific limitations

Scientific honesty matters more than sounding impressive. Read this before presenting results.

1. **Total-column vs surface ozone.** The Predictions page forecasts *surface* ozone (µg/m³, CAMS). The Location page shows NASA OMTO3G *total-column* ozone (Dobson Units). They are different quantities. Column ozone controls UV; surface ozone is the air-quality exposure. Never compare the two numbers.

2. **The "truth" is a model, not a measurement.** Both targets come from CAMS (an ECMWF chemistry-transport model with data assimilation). Our scores measure how well we reproduce CAMS hour-by-hour, not how well we match a ground monitor or a UV meter. CAMS surface ozone has known biases over South Asia. **Validation against CPCB stations was not possible** (no scriptable access; see blockers.md). Example: QC removed 26 Mumbai values of 602–930 µg/m³ that are physically implausible for ambient ozone; Mumbai's 99.9th percentile is still ~580 µg/m³, which is suspicious.

3. **Satellite resolution.** OMTO3G is 0.25°, once per day, with OMI's row anomaly; Aura science operations are expected to end by ~2028. TROPOMI is the successor (not yet integrated).

4. **Temporal resolution.** CAMS global is produced 3-hourly; Open-Meteo serves hourly values. Our test shows the intermediate hours are not plain linear interpolation (≈15 % of non-native ozone hours match linear), so hourly values are partly smoothed. Metrics are also reported on native hours only.

5. **Spatial representativeness.** CAMS cells are ~45 km. A city's street-level ozone (titration by traffic NO near roads, coastal effects) can differ strongly from the cell mean. NWP cells differ from CAMS cells (offsets recorded per location).

6. **No spatial interpolation, but limited spatial sampling.** Live inference queries providers at the exact clicked point, but the model was trained on 30 points. Generalisation was tested on 8 unseen points 150–300 km from the nearest training point. Points farther than 350 km from any training point (e.g. parts of far north Ladakh, the Andaman & Nicobar Islands, Lakshadweep) are marked "low" quality — accuracy NOT VERIFIED there.

7. **Weather-forecast uncertainty.** Live inputs are forecasts. In training, the archived forecasts are mostly short-lead, so live 18–24 h leads see somewhat worse weather inputs than the model saw in training. This probably makes the late-lead test scores slightly optimistic.

8. **UV estimation.** UV index depends on column ozone, clouds, aerosol, altitude and surface albedo. CAMS' cloud treatment differs from the NWP clouds we feed in; sudden convective clouds (monsoon) are hard for every model. The UV risk category is derived from the continuous forecast on the WHO scale and is not a health diagnosis.

9. **Missing observations.** Very few were missing (≤ 0.01 % per variable after QC). Values outside physical limits were set to NaN (not interpolated); tree models handle NaN natively.

10. **Model generalisation in time.** Training covers Aug 2022 – Sep 2024 (about 2 annual cycles). Unusual years (strong El Niño, extreme heat waves, changes in CAMS model versions) may behave differently. CAMS upgrades its model periodically, which can shift the target distribution (not modelled).

11. **Uncertainty ranges** are empirical 90 % split-conformal ranges calibrated on Oct 2024 – Sep 2025. They assume the future resembles that year. They are marginal (average) coverage per lead/level bin, not a guarantee for any single hour, and are not "confidence" scores.

12. **No comparison with CAMS' own 24-h forecast.** CAMS issues its own ozone/UV forecast. Without archived 24-h-lead CAMS forecasts (ADS account needed) we could not test whether OzoneGuard beats it. The API exposes the live CAMS raw forecast as `reference_cams_raw_forecast` for transparency.

13. **Correlation ≠ causation.** The correlation analysis describes co-variation (much of it the shared diurnal cycle). It does not show that one variable causes another.

14. **Geographic coverage.** 38 points: North 7, West 7, Central 5, East 5, Northeast 5, South 9. Rural, desert, high-altitude and island regimes are under-represented compared with cities.
