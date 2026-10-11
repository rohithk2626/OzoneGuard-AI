# Station ozone files for the ground-truth check

Put one CSV per monitoring station here, then run:

    python -m ml.validate_ground_truth csv data/external/stations/*.csv

Each file needs:

* a time column (`From Date`, `time`, `datetime`, `timestamp` or `date`), hourly, in Indian Standard Time unless you pass `--tz UTC`
* an ozone column (`Ozone` or `O3`) in µg/m³ (pass `--unit ppb` if the file is in ppb)
* the station's `latitude` and `longitude` as columns (the same value on every row), or `--lat` / `--lon` when you pass a single file

CPCB hourly exports from <https://airquality.cpcb.gov.in/ccr> can be used as downloaded once you add the station coordinates. Title rows above the header are skipped automatically.
