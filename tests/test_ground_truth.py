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


# ------------------------------------------------------------------ CPCB Excel downloads
def _cpcb_xlsx(path, as_text=False, missing_every=0):
    """A workbook laid out like a CPCB CCR download: title rows, then From Date / To Date / Ozone."""
    from openpyxl import Workbook
    wb = Workbook(); ws = wb.active
    for row in (["Central Control Room for Air Quality Management - All India"], ["Station Name: Test Park, Hyderabad - TSPCB"],
                ["Parameters: Ozone"], ["Criteria: 1 Hours"], []):
        ws.append(row)
    ws.append(["From Date", "To Date", "Ozone"])
    ist = HOURS.tz_convert("Asia/Kolkata").tz_localize(None)
    for i, (t, v) in enumerate(zip(ist, _truth().round(2))):
        start, end = t.to_pydatetime(), (t + pd.Timedelta(hours=1)).to_pydatetime()
        if as_text:
            start, end = start.strftime("%d-%m-%Y %H:%M"), end.strftime("%d-%m-%Y %H:%M")
        ws.append([start, end, "None" if missing_every and i % missing_every == 0 else float(v)])
    wb.save(path)
    return path


@pytest.mark.parametrize("as_text", [False, True])
def test_cpcb_excel_read_as_downloaded(tmp_path, as_text):
    """Real date cells and day-first text dates both land on the right UTC hour; coordinates and the
    station name come from the file name, so the download never has to be edited."""
    p = _cpcb_xlsx(tmp_path / "hyderabad_test_park_17.3500_78.4510.xlsx", as_text=as_text, missing_every=10)
    s = gt.read_station_file(p)
    assert s["time_utc"].min() == pd.Timestamp("2026-03-01T00:00Z")      # 01-03-2026 05:30 IST, not 3 January
    assert s["time_utc"].max() == HOURS.max()
    assert (s["latitude"].iloc[0], s["longitude"].iloc[0]) == (17.35, 78.451)
    assert s["station"].iloc[0] == "hyderabad test park"
    assert s["station_ozone"].isna().sum() == len(HOURS) // 10              # "None" cells become gaps
    out = gt.run(s, cams_fetch=_cams(bias=12.0))
    assert out["overall"]["bias"] == pytest.approx(12.0, abs=1.5)


def test_folder_and_wildcards_are_expanded(tmp_path):
    d = tmp_path / "stations"; d.mkdir()
    a = _cpcb_xlsx(d / "delhi_sirifort_28.5504_77.2159.xlsx")
    b = _generic_csv(d, name="hyderabad_zoo_17.3496_78.4512.csv")
    (d / "~$delhi_sirifort_28.5504_77.2159.xlsx").write_bytes(b"lock")   # Excel's lock file while it is open
    (d / "README.md").write_text("instructions")
    assert gt.expand_station_paths([d]) == sorted([a, b])
    assert gt.expand_station_paths([d / "*.xlsx"]) == [a]                 # PowerShell passes '*' literally
    with pytest.raises(ValueError):
        gt.expand_station_paths([tmp_path / "empty_folder_that_does_not_exist" / "*.xlsx"])


def test_missing_coordinates_message_explains_the_file_name(tmp_path):
    p = _cpcb_xlsx(tmp_path / "no_coordinates.xlsx")
    with pytest.raises(ValueError, match="End the file name with them"):
        gt.read_station_file(p)


def test_parts_of_one_station_are_combined(tmp_path):
    """A station downloaded in two date ranges (…_part1_…, …_part2_…) is one station in the report."""
    full = _generic_csv(tmp_path, name="full.csv")
    rows = pd.read_csv(full).drop(columns=["latitude", "longitude"])
    half = len(rows) // 2
    rows.iloc[:half].to_csv(tmp_path / "chennai_alandur_part1_13.0021_80.2016.csv", index=False)
    rows.iloc[half:].to_csv(tmp_path / "chennai_alandur_part2_13.0021_80.2016.csv", index=False)
    s = pd.concat([gt.read_station_file(p) for p in gt.expand_station_paths([tmp_path / "chennai_*.csv"])])
    assert set(s["station"]) == {"chennai alandur"}
    out = gt.run(s, cams_fetch=_cams(bias=5.0))
    assert len(out["stations"]) == 1 and out["stations"][0]["all"]["n"] >= len(HOURS) - 2


def _cpcb_repository_csv(path):
    """A file laid out like a CPCB 'CAAQMS Data Repository' download: year-first timestamps, every
    pollutant in its own column, 'NA' for missing values."""
    ist = HOURS.tz_convert("Asia/Kolkata").tz_localize(None)
    oz = pd.Series(_truth().round(2)).astype(object)
    oz[::25] = "NA"
    df = pd.DataFrame({"Timestamp": ist.strftime("%Y-%m-%d %H:%M:%S"), "PM2.5 (µg/m³)": 80.0, "NO2 (µg/m³)": 40.0,
                       "Ozone (µg/m³)": oz, "AT (°C)": 30.0})
    df.to_csv(path, index=False)
    return path


def test_cpcb_repository_csv_keeps_day_and_month(tmp_path):
    """Year-first timestamps must never be read day-first: 2026-03-12 is 12 March, not 3 December."""
    p = _cpcb_repository_csv(tmp_path / "Raw_Data_2026_site_298_zoo_park_hyderabad_tspcb_1Hr_17.3496_78.4512.csv")
    s = gt.read_station_file(p).set_index("time_utc")
    assert s.index.min() == pd.Timestamp("2026-03-01T00:00Z") and s.index.max() == HOURS.max()
    t = pd.Timestamp("2026-03-12 13:00", tz="Asia/Kolkata").tz_convert("UTC").floor("h")
    assert s.loc[t, "station_ozone"] == pytest.approx(_truth().round(2)[HOURS.get_loc(t)])
    assert s["station"].iloc[0] == "zoo park hyderabad tspcb"           # CPCB prefix and '_1Hr' removed
    assert s["station_ozone"].isna().sum() == len(HOURS) // 25 + 1        # 'NA' cells become gaps
    out = gt.run(s.reset_index(), cams_fetch=_cams(bias=-6.0))
    assert out["overall"]["bias"] == pytest.approx(-6.0, abs=1.5) and out["stations"][0]["r_by_cams_shift_hours"]["0"] > 0.9


def test_two_years_of_one_station_are_combined(tmp_path):
    a = _cpcb_repository_csv(tmp_path / "Raw_Data_2025_site_298_zoo_park_hyderabad_tspcb_1Hr_17.3496_78.4512.csv")
    b = _cpcb_repository_csv(tmp_path / "Raw_Data_2026_site_298_zoo_park_hyderabad_tspcb_1Hr_17.3496_78.4512.csv")
    names = {gt.read_station_file(p)["station"].iloc[0] for p in (a, b)}
    assert names == {"zoo park hyderabad tspcb"}
