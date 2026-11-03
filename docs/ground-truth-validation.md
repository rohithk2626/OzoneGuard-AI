# Ground-truth check: CAMS surface ozone against station measurements

Generated 2026-11-03 07:47 UTC by `python -m ml.validate_ground_truth`. Station data: 7 station file(s): Raw_Data_2025_site_119_sirifort_delhi_cpcb_1Hr_28.5533_77.2108.csv, Raw_Data_2025_site_1554_hebbal_bengaluru_kspcb_1Hr_13.0400_77.5900.csv, Raw_Data_2025_site_1558_silk_board_bengaluru_kspcb_1Hr_12.9170_77.6230.csv, Raw_Data_2025_site_293_alandur_bus_depot_chennai_cpcb_1Hr_12.9975_80.2006.csv, Raw_Data_2025_site_309_victoria_kolkata_wbpcb_1Hr_22.5449_88.3425.csv, Raw_Data_2025_site_5598_somajiguda_hyderabad_tspcb_1Hr_17.4289_78.4553.csv, Raw_Data_2025_site_5810_bandra_kurla_complex_mumbai_mpcb_1Hr_19.0565_72.8534.csv.

The forecast models are trained on CAMS, which is itself a model. This report compares CAMS with real
station readings for the same place and hour. Bias is CAMS minus station, so a positive bias means CAMS reads higher.

## Overall

* Stations compared: **7**, matched hours: **56,581**
* Station average **23.3** µg/m³, CAMS average **86.9** µg/m³
* Bias **+63.6** µg/m³, average error (MAE) **65.3** µg/m³, RMSE **78.0** µg/m³, correlation r = **0.47**

### What this means

* CAMS reads **higher** than the stations by 63.6 µg/m³ on average.
* The forecast's tested error (about 10.6 µg/m³) is measured against CAMS. Against real air the total
  error cannot be smaller than the CAMS-to-station gap above (65.3 µg/m³ on average).
* A station measures one street; a CAMS value covers a square about 45 km wide. Some of the gap is this
  difference in scale, not an error in either number.

## Per station

| Station | Lat | Lon | Hours | Station avg | CAMS avg | Bias | MAE | RMSE | r | r daytime | r night |
|---|---|---|---|---|---|---|---|---|---|---|---|
| alandur bus depot chennai cpcb | 12.998 | 80.201 | 7,424 | 26.0 | 87.6 | +61.6 | 67.5 | 75.6 | 0.07 | 0.14 | -0.02 |
| bandra kurla complex mumbai mpcb | 19.056 | 72.853 | 8,400 | 26.6 | 101.1 | +74.6 | 75.2 | 91.4 | 0.72 | 0.71 | 0.40 |
| hebbal bengaluru kspcb | 13.040 | 77.590 | 8,293 | 11.9 | 73.7 | +61.8 | 62.0 | 71.0 | 0.47 | 0.48 | 0.26 |
| silk board bengaluru kspcb | 12.917 | 77.623 | 7,684 | 22.2 | 72.1 | +49.9 | 51.1 | 62.5 | 0.34 | 0.43 | 0.08 |
| sirifort delhi cpcb | 28.553 | 77.211 | 8,689 | 26.2 | 91.4 | +65.1 | 68.8 | 86.4 | 0.29 | 0.19 | 0.27 |
| somajiguda hyderabad tspcb | 17.429 | 78.455 | 7,585 | 24.6 | 91.9 | +67.3 | 67.4 | 76.6 | 0.52 | 0.43 | 0.22 |
| victoria kolkata wbpcb | 22.545 | 88.343 | 8,506 | 25.9 | 89.5 | +63.7 | 63.9 | 77.0 | 0.68 | 0.54 | 0.34 |

### Clock alignment

Correlation when the CAMS series is shifted by −1, 0 and +1 hour. If a shift other than 0 is clearly best,
the station timestamps and CAMS are not labelled the same way and the numbers above are pessimistic.

| Station | −1 h | 0 h | +1 h |
|---|---|---|---|
| alandur bus depot chennai cpcb | 0.07 | 0.07 | 0.07 |
| bandra kurla complex mumbai mpcb | 0.74 | 0.72 | 0.63 |
| hebbal bengaluru kspcb | 0.48 | 0.47 | 0.44 |
| silk board bengaluru kspcb | 0.35 | 0.34 | 0.32 |
| sirifort delhi cpcb | 0.27 | 0.29 | 0.30 |
| somajiguda hyderabad tspcb | 0.53 | 0.52 | 0.47 |
| victoria kolkata wbpcb | 0.71 | 0.68 | 0.60 |

## Data cleaning per station

| Station | Rows read | Missing | Out of range | Stuck sensor | Note |
|---|---|---|---|---|---|
| alandur bus depot chennai cpcb | 8,760 | 1,323 | 0 | 13 |  |
| bandra kurla complex mumbai mpcb | 8,760 | 360 | 0 | 0 |  |
| hebbal bengaluru kspcb | 8,760 | 467 | 0 | 0 |  |
| silk board bengaluru kspcb | 8,760 | 1,052 | 0 | 24 |  |
| sirifort delhi cpcb | 8,760 | 71 | 0 | 0 |  |
| somajiguda hyderabad tspcb | 8,760 | 895 | 0 | 280 |  |
| victoria kolkata wbpcb | 8,760 | 254 | 0 | 0 |  |

Readings outside 0–600 µg/m³ are dropped, as are runs of 12 or more identical non-zero hours (a stuck sensor).
A station needs at least 100 matched hours. Full numbers: `data/validation/ground_truth_metrics.json`.
