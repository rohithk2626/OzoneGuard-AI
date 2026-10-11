"""Ground-truth check tests on synthetic station data with a known relation to "CAMS"."""
import json

import numpy as np
import pandas as pd
import pytest

from ml import validate_ground_truth as gt

HOURS = pd.date_range("2026-03-01T00:00Z", periods=24 * 30, freq="h")


def _truth():
    """A realistic daily ozone cycle (µg/m³) plus noise, indexed by UTC hour."""
    rng = np.random.default_rng(7)
    ist = (np.asarray(HOURS.hour, dtype=float) + 5.5) % 24
    return 60 + 45 * np.clip(np.sin((ist - 7) / 12 * np.pi), 0, None) + rng.normal(0, 4, len(HOURS))


def _cams(bias=12.0, shift_hours=0):
    rng = np.random.default_rng(8)
    def fetch(lat, lon, start, end):
        return pd.DataFrame({"time_utc": HOURS + pd.Timedelta(hours=shift_hours), "cams_ozone": _truth() + bias + rng.normal(0, 6, len(HOURS))})
    return fetch


def _generic_csv(tmp_path, values=None, name="station_a.csv"):
    ist = HOURS.tz_convert("Asia/Kolkata").strftime("%d-%m-%Y %H:%M")
    df = pd.DataFrame({"From Date": ist, "Ozone": _truth() if values is None else values, "latitude": 17.4, "longitude": 78.5})
    p = tmp_path / name
    df.to_csv(p, index=False)
    return p


def test_ist_times_are_converted_to_utc(tmp_path):
    s = gt.read_station_csv(_generic_csv(tmp_path))
    assert str(s["time_utc"].dt.tz) == "UTC" and len(s) >= len(HOURS) - 1
    # 01-03-2026 05:30 IST is 2026-03-01 00:00 UTC; flooring a :30 offset to the hour keeps 00:00
    assert s["time_utc"].min() == pd.Timestamp("2026-03-01T00:00Z")
    assert s["latitude"].iloc[0] == 17.4 and s["station"].iloc[0] == "station_a"


def test_cpcb_style_export_with_title_rows(tmp_path):
    ist = HOURS.tz_convert("Asia/Kolkata")
    body = pd.DataFrame({"From Date": ist.strftime("%d-%m-%Y %H:%M"), "To Date": (ist + pd.Timedelta(hours=1)).strftime("%d-%m-%Y %H:%M"), "Ozone": _truth().round(2)})
    p = tmp_path / "cpcb.csv"
    p.write_text("Station: Test Station - CPCB\nParameters: Ozone\nAvg Period: 1 Hr\n\n" + body.to_csv(index=False), encoding="utf-8")
    s = gt.read_station_csv(p, lat=28.6, lon=77.2)
    assert len(s) >= len(HOURS) - 1 and s["station_ozone"].between(0, 200).all() and s["longitude"].iloc[0] == 77.2
    with pytest.raises(ValueError):
        gt.read_station_csv(p)                                  # no coordinates anywhere


def test_metrics_recover_a_known_bias(tmp_path):
    out = gt.run(gt.read_station_csv(_generic_csv(tmp_path)), cams_fetch=_cams(bias=12.0))
    st, o = out["stations"][0], out["overall"]
    assert o["bias"] == pytest.approx(12.0, abs=1.0)            # CAMS minus station
    assert 11 < o["mae"] < 15 and o["rmse"] >= o["mae"] and o["r"] > 0.85
    assert st["daytime_09_17_ist"]["n"] + st["night"]["n"] == st["all"]["n"]
    assert len(st["average_day_ist"]) == 24
    lag = st["r_by_cams_shift_hours"]
    assert lag["0"] > lag["-1"] and lag["0"] > lag["1"]         # clocks aligned -> no shift is best


def test_clock_misalignment_is_detected(tmp_path):
    out = gt.run(gt.read_station_csv(_generic_csv(tmp_path)), cams_fetch=_cams(shift_hours=1))
    lag = out["stations"][0]["r_by_cams_shift_hours"]
    assert lag["-1"] > lag["0"]                                 # shifting CAMS back an hour fits better


def test_bad_readings_are_removed(tmp_path):
    v = _truth()
    v[10] = -5; v[11] = 9999; v[100:120] = 77.7                 # impossible values and a stuck sensor
    v = v.astype(object); v[12] = ""
    out = gt.run(gt.read_station_csv(_generic_csv(tmp_path, v)), cams_fetch=_cams())
    qc = out["stations"][0]["qc"]
    assert qc["out_of_range"] == 2 and qc["stuck_sensor"] == 20 and qc["missing"] == 1
    assert out["overall"]["bias"] == pytest.approx(12.0, abs=1.5)


def test_ppb_conversion_and_too_few_hours(tmp_path):
    p = _generic_csv(tmp_path, _truth() / gt.PPB_TO_UGM3)
    assert gt.read_station_csv(p, unit="ppb")["station_ozone"].mean() == pytest.approx(_truth().mean(), rel=0.01)
    short = gt.read_station_csv(p).head(50)
    out = gt.run(short, cams_fetch=_cams())
    assert out["overall"] is None and "fewer than" in out["stations"][0]["error"]


def test_report_files(tmp_path):
    out = gt.run(gt.read_station_csv(_generic_csv(tmp_path)), cams_fetch=_cams())
    md, js = tmp_path / "r.md", tmp_path / "v" / "m.json"
    gt.write_report(out, md, js)
    text = md.read_text(encoding="utf-8")
    assert "CAMS reads **higher**" in text and "| station_a |" in text and "Clock alignment" in text
    assert json.loads(js.read_text(encoding="utf-8"))["overall"]["n"] == out["overall"]["n"]
