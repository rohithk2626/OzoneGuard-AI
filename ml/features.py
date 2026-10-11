"""Feature engineering shared by TRAINING and LIVE INFERENCE.

Forecast formulation: DIRECT multi-horizon. One row = (location, issue time t,
lead h ∈ 1..24). Target = value at T = t + h. A single model per target is
trained across all horizons with ``lead_h`` as a feature (benchmarked against
per-horizon models in ml/train.py).

Information-set rule (enforced by tests/test_ml_leakage.py):
* CAMS values (ozone, UV, NO2, AOD) are used ONLY at times <= t.
* Weather at T comes from a weather FORECAST (archived NWP forecasts in
  training, live Open-Meteo forecast at inference) -- never from observations.
* Solar geometry and calendar terms at T are deterministic.

``build_rows`` takes one location's continuous hourly frame and returns the
feature rows; it is the single implementation used by both paths.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ml import config
from ml.solar import solar_position

WX_FC = ["temperature_2m", "relative_humidity_2m", "dew_point_2m", "surface_pressure", "cloud_cover",
         "precipitation", "shortwave_radiation", "wind_speed_10m", "uv_index", "uv_index_clear_sky"]

LAG_SOURCES = {"ozone": "cams_ozone", "uv": "cams_uv_index", "no2": "cams_nitrogen_dioxide",
               "aod": "cams_aerosol_optical_depth"}

COMMON_FEATURES = [
    "lead_h", "lat", "lon", "elevation_m",
    "sin_doy", "cos_doy", "sin_solar_time", "cos_solar_time",
    "solar_elevation", "cos_zenith", "earth_sun_distance_au", "daylight_hours",
    "fc_temperature_2m", "fc_relative_humidity_2m", "fc_dew_point_2m", "fc_surface_pressure",
    "fc_cloud_cover", "fc_precipitation", "fc_shortwave_radiation", "fc_wind_speed_10m",
    "fc_wind_dir_sin", "fc_wind_dir_cos", "fc_uv_index", "fc_uv_index_clear_sky",
    "fc_cloud_mean_6h",
]


def lag_features(prefix: str) -> list[str]:
    return [f"{prefix}_t", f"{prefix}_t_minus3", f"{prefix}_same_hour_prev_day",
            f"{prefix}_same_hour_2days", f"{prefix}_mean_24h", f"{prefix}_max_24h"]


OZONE_FEATURES = COMMON_FEATURES + lag_features("ozone") + ["no2_t", "no2_mean_24h", "aod_t", "aod_mean_24h"]
UV_FEATURES_NO_OZONE = COMMON_FEATURES + lag_features("uv") + ["aod_t", "aod_mean_24h"]
UV_FEATURES_WITH_OZONE_LAGS = UV_FEATURES_NO_OZONE + lag_features("ozone")
UV_FEATURES_WITH_PRED_OZONE = UV_FEATURES_NO_OZONE + ["pred_ozone"]


def build_rows(frame: pd.DataFrame, issue_times, lat: float, lon: float, elevation_m: float | None,
               horizons=config.HORIZONS, include_targets: bool = True) -> pd.DataFrame:
    """Build direct multi-horizon feature rows for one location.

    ``frame``: continuous hourly UTC index (``time_utc``) with ``cams_*`` and
    ``wx_*`` columns. At inference the cams_* columns are NaN after t and the
    wx_* columns hold the live forecast.
    """
    f = frame.set_index("time_utc").sort_index()
    if not f.index.is_unique:
        raise ValueError("duplicate timestamps in frame")
    full = pd.date_range(f.index.min(), f.index.max(), freq="h", tz="UTC")
    f = f.reindex(full)
    issue_times = pd.DatetimeIndex(pd.to_datetime(issue_times, utc=True))
    issue_times = issue_times[issue_times.isin(f.index)]

    # ---- lag features evaluated at issue time t (only data <= t) -------------
    lag = pd.DataFrame(index=f.index)
    for prefix, col in LAG_SOURCES.items():
        s = f[col] if col in f else pd.Series(np.nan, index=f.index)
        lag[f"{prefix}_t"] = s
        lag[f"{prefix}_t_minus3"] = s.shift(3)
        lag[f"{prefix}_mean_24h"] = s.rolling(24, min_periods=18).mean()   # window t-23..t
        lag[f"{prefix}_max_24h"] = s.rolling(24, min_periods=18).max()

    out = []
    for h in horizons:
        T = issue_times + pd.Timedelta(hours=h)
        ok = T.isin(f.index)
        t_ok, T_ok = issue_times[ok], T[ok]
        r = pd.DataFrame({"issue_time": t_ok, "target_time": T_ok, "lead_h": h})
        L = lag.loc[t_ok].reset_index(drop=True)
        r = pd.concat([r, L], axis=1)
        # same hour previous day / two days relative to TARGET (both <= t because h <= 24)
        for prefix, col in LAG_SOURCES.items():
            if prefix not in ("ozone", "uv"):
                continue
            s = f[col] if col in f else pd.Series(np.nan, index=f.index)
            r[f"{prefix}_same_hour_prev_day"] = s.reindex(T_ok - pd.Timedelta(hours=24)).to_numpy()
            r[f"{prefix}_same_hour_2days"] = s.reindex(T_ok - pd.Timedelta(hours=48)).to_numpy()
        # weather forecast valid at T
        for v in WX_FC:
            r[f"fc_{v}"] = f[f"wx_{v}"].reindex(T_ok).to_numpy()
        wd = np.radians(f["wx_wind_direction_10m"].reindex(T_ok).to_numpy())
        r["fc_wind_dir_sin"], r["fc_wind_dir_cos"] = np.sin(wd), np.cos(wd)
        cloud6 = f["wx_cloud_cover"].rolling(6, min_periods=3).mean()  # forecast cloud T-5..T
        r["fc_cloud_mean_6h"] = cloud6.reindex(T_ok).to_numpy()
        if include_targets:
            for name, col in config.TARGETS.items():
                r[f"y_{name}"] = f[col].reindex(T_ok).to_numpy() if col in f else np.nan
            r["target_native"] = (T_ok.hour % 3 == 0)
        out.append(r)
    rows = pd.concat(out, ignore_index=True)

    # ---- deterministic geometry / calendar at T --------------------------------
    sp = solar_position(rows["target_time"], lat, lon)
    rows["solar_elevation"] = sp["solar_elevation"]
    rows["cos_zenith"] = sp["cos_zenith"]
    rows["earth_sun_distance_au"] = sp["earth_sun_distance_au"]
    rows["daylight_hours"] = sp["daylight_hours"]
    st = sp["true_solar_time_min"] / 1440.0 * 2 * np.pi
    rows["sin_solar_time"], rows["cos_solar_time"] = np.sin(st), np.cos(st)
    doy = rows["target_time"].dt.dayofyear.to_numpy()
    rows["sin_doy"], rows["cos_doy"] = np.sin(2 * np.pi * doy / 365.25), np.cos(2 * np.pi * doy / 365.25)
    rows["lat"], rows["lon"] = lat, lon
    rows["elevation_m"] = elevation_m if elevation_m is not None else np.nan
    return rows


def build_training_table(clean: pd.DataFrame) -> pd.DataFrame:
    parts = []
    for lid, g in clean.groupby("location_id"):
        first = g.iloc[0]
        issue = g.loc[g["time_utc"].dt.hour.isin(config.ISSUE_HOURS_UTC), "time_utc"]
        rows = build_rows(g, issue, float(first.req_lat), float(first.req_lon), float(first.wx_elev))
        rows["location_id"], rows["region"], rows["role"] = lid, first.region, first.role
        parts.append(rows)
    df = pd.concat(parts, ignore_index=True)
    return df


def assign_split(df: pd.DataFrame) -> pd.Series:
    """Chronological split on issue time with purging of boundary-crossing rows."""
    train_end = pd.Timestamp(config.TRAIN_END)
    val_end = pd.Timestamp(config.VAL_END)
    split = pd.Series("test", index=df.index)
    split[df["issue_time"] <= val_end] = "val"
    split[df["issue_time"] <= train_end] = "train"
    # purge: training rows whose target falls in validation, val rows whose target is in test
    split[(split == "train") & (df["target_time"] > train_end)] = "purged"
    split[(split == "val") & (df["target_time"] > val_end)] = "purged"
    split[df["role"] == "spatial_holdout"] = "holdout_" + split[df["role"] == "spatial_holdout"]
    return split


def main() -> None:
    clean = pd.read_parquet(config.INTERMEDIATE / "cleaned.parquet")
    table = build_training_table(clean)
    table["split"] = assign_split(table)
    config.PROCESSED.mkdir(parents=True, exist_ok=True)
    for name in ["train", "val", "test"]:
        part = table[table["split"] == name]
        part.to_parquet(config.PROCESSED / f"{name}.parquet", index=False)
    hold = table[table["split"].str.startswith("holdout_")]
    hold.to_parquet(config.PROCESSED / "spatial_holdout.parquet", index=False)
    summary = table.groupby("split").agg(rows=("lead_h", "size"), start=("issue_time", "min"), end=("issue_time", "max"))
    print(summary)


if __name__ == "__main__":
    main()
