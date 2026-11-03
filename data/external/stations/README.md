# Station ozone files for the ground-truth check

Put one or more files per monitoring station here, then run from the project folder:

    python -m ml.validate_ground_truth csv data/external/stations

(On Windows: `.\.venv\Scripts\python.exe -m ml.validate_ground_truth csv data\external\stations`.)

**Where the files come from.** CPCB portal <https://airquality.cpcb.gov.in/ccr> → menu **Data → CAAQMS
Data Repository** → choose State, City and Station → Frequency **1H** → **Submit** → the **↓** arrow on a
year's row. The download is a CSV such as `Raw_Data_2025_site_298_zoo_park_hyderabad_tspcb_1Hr.csv`,
with a `Timestamp` column (Indian Standard Time) and one column per pollutant; only `Ozone (µg/m³)`
is used. Use the file as downloaded: do not open and re-save it in Excel, which can rewrite the dates.

**Coordinates.** Add the station's latitude and longitude to the end of the file name, separated by
underscores, and keep everything else:

    Raw_Data_2025_site_298_zoo_park_hyderabad_tspcb_1Hr_17.3496_78.4512.csv

CPCB's `Raw_Data_<year>_site_<id>_` and `_1Hr` parts are left out of the station's name in the report
("zoo park hyderabad tspcb"), so several years of one station are combined. Short names work too
(`hyderabad_zoo_park_17.3496_78.4512.csv`), as do `latitude`/`longitude` columns in the file, or
`--lat` / `--lon` when you pass a single file.

**Other formats.** CPCB Excel exports (`.xlsx`, title rows above a `From Date` / `Ozone` table) are read
as well. Year-first dates (`2025-01-12`) are read year-month-day; other text dates (`12-01-2025`) day
first. Pass `--unit ppb` if ozone is in ppb, or `--tz UTC` if the times are in UTC. Excel's temporary
`~$…` files and this README are ignored.

Each station needs at least 100 hours that overlap CAMS (August 2022 onwards); a full year is best.
The results are written to `docs/ground-truth-validation.md` and `data/validation/ground_truth_metrics.json`.
