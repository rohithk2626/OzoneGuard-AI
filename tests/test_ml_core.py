import numpy as np
import pandas as pd
import pytest

from ml import config
from ml.features import (OZONE_FEATURES, UV_FEATURES_NO_OZONE, assign_split, build_rows)
from ml.preprocess import clean
from ml.risk import uv_risk_index, uv_risk_label
from ml.solar import solar_position
from tests._synthetic import synthetic_frame


# ---------------------------------------------------------------- solar / time
def test_solar_noon_elevation_hyderabad_june():
    t = pd.date_range("2024-06-21", periods=24 * 60, freq="min", tz="UTC")
    el = solar_position(t, 17.385, 78.487)["solar_elevation"]
    # max elevation = 90 - |lat - decl| ≈ 90 - (23.44 - 17.385) ≈ 83.9°
    assert el.max() == pytest.approx(83.94, abs=0.15)
    noon = t[int(np.argmax(el))]
    assert noon.hour == 6 and 40 <= noon.minute <= 52  # ~12:16 IST


def test_solar_night_negative():
    el = solar_position(pd.DatetimeIndex(["2024-01-01T20:00:00Z"]), 17.385, 78.487)["solar_elevation"]
    assert el[0] < 0  # 01:30 IST


def test_timestamps_are_utc():
    rows = build_rows(synthetic_frame(), [pd.Timestamp("2024-03-03T06:00:00Z")], 17.0, 78.0, 500.0)
    assert str(rows["target_time"].dt.tz) == "UTC"
    assert rows["target_time"].min() == pd.Timestamp("2024-03-03T07:00:00Z")


# ---------------------------------------------------------------- risk scale
@pytest.mark.parametrize("uv,label", [(0, "Low"), (2.49, "Low"), (2.5, "Moderate"), (5.4, "Moderate"), (5.5, "High"),
                                      (7.49, "High"), (7.5, "Very High"), (10.49, "Very High"), (10.5, "Extreme"), (14, "Extreme")])
def test_who_uv_scale(uv, label):
    assert uv_risk_label(uv) == label


def test_risk_unavailable():
    assert uv_risk_label(None) == "Unavailable"
    assert uv_risk_label(float("nan")) == "Unavailable"


# ---------------------------------------------------------------- features
def test_horizon_count_and_lags():
    f = synthetic_frame()
    t = pd.Timestamp("2024-03-04T00:00:00Z")
    rows = build_rows(f, [t], 17.0, 78.0, 500.0)
    assert sorted(rows["lead_h"]) == list(range(1, 25))
    idx_t = int((t - f["time_utc"][0]) / pd.Timedelta(hours=1))
    r5 = rows[rows["lead_h"] == 5].iloc[0]
    assert r5["ozone_t"] == idx_t + 1000                      # latest value at t
    assert r5["ozone_t_minus3"] == idx_t - 3 + 1000
    assert r5["ozone_same_hour_prev_day"] == idx_t + 5 - 24 + 1000
    assert r5["ozone_same_hour_2days"] == idx_t + 5 - 48 + 1000
    assert r5["ozone_mean_24h"] == pytest.approx(np.mean(np.arange(idx_t - 23, idx_t + 1)) + 1000)
    assert r5["fc_temperature_2m"] == idx_t + 5 + 100000      # weather FORECAST valid at T
    assert r5["y_ozone"] == idx_t + 5 + 1000


def test_no_future_composition_leakage():
    """Changing any CAMS value after the issue time must not change any feature."""
    f = synthetic_frame()
    t = pd.Timestamp("2024-03-04T00:00:00Z")
    a = build_rows(f, [t], 17.0, 78.0, 500.0, include_targets=False)
    g = f.copy()
    cams = [c for c in g.columns if c.startswith("cams_")]
    g.loc[g["time_utc"] > t, cams] = -999.0
    b = build_rows(g, [t], 17.0, 78.0, 500.0, include_targets=False)
    feats = sorted(set(OZONE_FEATURES) | set(UV_FEATURES_NO_OZONE))
    pd.testing.assert_frame_equal(a[feats], b[feats])


def test_targets_never_in_feature_lists():
    for feats in (OZONE_FEATURES, UV_FEATURES_NO_OZONE):
        assert not any(c.startswith("y_") for c in feats)
        assert "cams_ozone" not in feats and "cams_uv_index" not in feats


def test_split_purges_boundary_rows():
    df = pd.DataFrame({
        "issue_time": pd.to_datetime(["2024-09-30T22:00Z", "2024-09-30T12:00Z", "2025-09-30T20:00Z", "2025-10-01T00:00Z"]),
        "target_time": pd.to_datetime(["2024-10-01T05:00Z", "2024-09-30T20:00Z", "2025-10-01T02:00Z", "2025-10-01T05:00Z"]),
        "role": ["train"] * 4})
    s = assign_split(df).tolist()
    assert s == ["purged", "train", "purged", "test"]


def test_spatial_holdout_never_in_train():
    df = pd.DataFrame({"issue_time": pd.to_datetime(["2023-01-01T00:00Z"]),
                       "target_time": pd.to_datetime(["2023-01-01T05:00Z"]), "role": ["spatial_holdout"]})
    assert assign_split(df).iloc[0] == "holdout_train"


# ---------------------------------------------------------------- QC / alignment
def _raw():
    f = synthetic_frame(48, start="2024-01-01T00:00:00Z")
    f["cams_ozone"] = 50.0
    f["cams_uv_index"] = 0.0
    f["wx_relative_humidity_2m"] = 50.0
    f["wx_surface_pressure"] = 950.0
    meta = dict(location_id="x", name="X", region="South", role="train", req_lat=17.0, req_lon=78.0,
                aq_lat=17.0, aq_lon=78.0, aq_elev=500.0, wx_lat=17.01, wx_lon=78.02, wx_elev=505.0)
    for k, v in meta.items():
        f[k] = v
    return f


def test_qc_duplicates_gaps_limits():
    f = _raw()
    f.loc[3, "cams_ozone"] = 5000.0                       # physically impossible
    f.loc[4, "wx_relative_humidity_2m"] = 140.0
    f = pd.concat([f, f.iloc[[10]]])                    # duplicate
    f = f.drop(index=20)                                 # gap
    df, rep = clean(f)
    assert rep["duplicate_rows_removed"] == 1
    assert rep["missing_timestamps_inserted"]["x"] == 1
    assert rep["values_outside_physical_limits_set_nan"]["cams_ozone"] == 1
    assert rep["values_outside_physical_limits_set_nan"]["wx_relative_humidity_2m"] == 1
    assert df["time_utc"].diff().dropna().eq(pd.Timedelta(hours=1)).all()
    assert len(df) == 48                                  # rows kept, bad values -> NaN
    assert df["cams_ozone"].isna().sum() == 2             # impossible value + inserted gap
    assert rep["spatial_alignment"]["x"]["nwp_cell_offset_km"] > 0


def test_climatology_uses_training_period_only():
    from ml.train import build_climatology
    f = _raw()
    f["time_utc"] = pd.date_range("2024-09-30T00:00Z", periods=48, freq="h")  # spans TRAIN_END
    f.loc[f["time_utc"] > pd.Timestamp(config.TRAIN_END), "cams_ozone"] = 10_000.0
    f["req_lat"], f["req_lon"] = 17.0, 78.0
    clim = build_climatology(f)
    assert clim["ozone_mean"].max() == 50.0
