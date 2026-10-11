"""Analytics (PAST) tests.

History is replayed from the REAL Hyderabad extract in data/samples (CAMS + archived
NWP forecast, 28 Sep - 2 Oct 2026) shaped like Open-Meteo responses, so no network is needed.
"""
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.services import analytics_service as an
from ml import config

client = TestClient(app)
SAMPLE = Path(config.SAMPLES) / "hyderabad_frame_2026-09-28_to_10-02.parquet"
START, END = date(2026, 9, 29), date(2026, 10, 1)          # three complete Indian days inside the sample
NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
TODAY = date(2026, 10, 7)


def _payloads():
    """The sample frame as the two Open-Meteo JSON payloads (hourly, GMT)."""
    f = pd.read_parquet(SAMPLE).sort_values("time_utc")
    t = f["time_utc"].dt.strftime("%Y-%m-%dT%H:%M").tolist()

    def col(name):
        return [None if pd.isna(v) else float(v) for v in f[name]]

    aq = {"latitude": 17.4, "longitude": 78.5, "hourly": {
        "time": t, "ozone": col("cams_ozone"), "uv_index": col("cams_uv_index"),
        "nitrogen_dioxide": col("cams_nitrogen_dioxide"), "aerosol_optical_depth": col("cams_aerosol_optical_depth")}}
    wx = {"latitude": 17.39, "longitude": 78.46, "elevation": 505.0, "hourly": {
        "time": t, **{v: col(f"wx_{v}") for v in an.WX_VARS}}}
    return aq, wx


def _fake_fetch(calls=None):
    aq, wx = _payloads()

    def fetch(url, params):
        if calls is not None:
            calls.append((url, params))
        return aq if url == an.AQ_URL else wx
    return fetch


def _frame(monkeypatch):
    monkeypatch.setattr(an, "_fetch", _fake_fetch())
    return an.fetch_hourly(17.385, 78.4867, START, END)[0]


def test_range_validation():
    an.validate_range(date(2026, 9, 1), date(2026, 9, 30), today=TODAY)
    for bad in [(date(2026, 9, 30), date(2026, 9, 1)),          # start after end
                (date(2026, 10, 1), date(2026, 10, 8)),         # future
                (date(2022, 8, 3), date(2022, 9, 1)),           # before the CAMS record
                (date(2025, 1, 1), date(2026, 6, 1))]:          # longer than 366 days
        with pytest.raises(an.InvalidRange):
            an.validate_range(*bad, today=TODAY)


def test_fetch_uses_training_request_shape(monkeypatch):
    calls = []
    monkeypatch.setattr(an, "_fetch", _fake_fetch(calls))
    frame, meta = an.fetch_hourly(17.385, 78.4867, START, END)
    assert [c[0] for c in calls] == [an.AQ_URL, an.HF_URL]
    for _, p in calls:                                           # one extra day each side covers the IST offset
        assert p["start_date"] == "2026-09-28" and p["end_date"] == "2026-10-02" and p["timezone"] == "GMT"
    assert calls[0][1]["domains"] == "cams_global"
    assert str(frame["time_utc"].dt.tz) == "UTC" and len(frame) == 120
    assert meta["elevation_m"] == 505.0


def test_daily_summary_is_real_and_physical(monkeypatch):
    out = an.summarise(_frame(monkeypatch), START, END, now=NOW)
    days = out["daily"]
    assert [d["date"] for d in days] == ["2026-09-29", "2026-09-30", "2026-10-01"]
    for d in days:
        assert d["hours"] == 24 and d["partial"] is False
        assert 0 < d["ozone_mean"] <= d["ozone_max"] < 600
        assert 0 < d["uv_max"] < 16 and d["uv_risk"] in ["Low", "Moderate", "High", "Very High", "Extreme"]
        assert d["temp_min"] <= d["temp_mean"] <= d["temp_max"]
    avg = {h["hour_ist"]: h for h in out["average_day"]}
    assert len(avg) == 24
    assert avg[0]["uv"] == 0 and avg[23]["uv"] == 0             # no UV at night (IST)
    assert 10 <= max(avg, key=lambda h: avg[h]["uv"]) <= 14      # UV peaks around midday IST
    s = out["summary"]
    assert s["days"] == 3 and s["full_days"] == 3 and s["hours"] == 72
    assert sum(s["uv_risk_days"].values()) == 3
    assert s["highest_uv"]["value"] == max(d["uv_max"] for d in days)
    r = out["relationships"]["ozone_vs_sunlight"]
    assert r["n"] >= 24 and -1 <= r["r"] <= 1


def test_ist_day_grouping(monkeypatch):
    """29 Sep IST runs from 28 Sep 18:30 UTC to 29 Sep 18:30 UTC."""
    f = _frame(monkeypatch)
    out = an.summarise(f, date(2026, 9, 29), date(2026, 9, 29), now=NOW)
    lo, hi = pd.Timestamp("2026-09-28T18:30Z"), pd.Timestamp("2026-09-29T18:30Z")
    expect = f[(f["time_utc"] >= lo) & (f["time_utc"] < hi)]["ozone"].mean()
    assert out["daily"][0]["ozone_mean"] == pytest.approx(expect, abs=0.06)


def test_future_hours_are_never_reported(monkeypatch):
    now = datetime(2026, 10, 1, 6, 0, tzinfo=timezone.utc)       # 11:30 IST on 1 Oct
    out = an.summarise(_frame(monkeypatch), START, END, now=now)
    last = out["daily"][-1]
    assert last["date"] == "2026-10-01" and last["partial"] is True and last["hours"] == 12
    assert out["summary"]["full_days"] == 2


def test_no_data_is_an_error_not_zeros(monkeypatch):
    f = _frame(monkeypatch)
    f[["ozone", "uv_index"]] = float("nan")
    with pytest.raises(an.AnalyticsUnavailable):
        an.summarise(f, START, END, now=NOW)


def test_route(monkeypatch):
    monkeypatch.setattr(an, "_fetch", _fake_fetch())
    monkeypatch.setattr(an, "today_ist", lambda: TODAY)
    monkeypatch.setattr("backend.api.routes.analytics.today_ist", lambda: TODAY)
    an._cache.clear()
    r = client.get("/api/v1/analytics/history?lat=17.385&lon=78.4867&start=2026-09-29&end=2026-10-01")
    assert r.status_code == 200
    body = r.json()
    assert len(body["daily"]) == 3 and body["units"]["ozone"].startswith("µg/m³")
    assert body["period"] == {"start": "2026-09-29", "end": "2026-10-01", "timezone": "Asia/Kolkata (IST, UTC+5:30)"}
    assert client.get("/api/v1/analytics/history?lat=15&lon=88").status_code == 400                       # Bay of Bengal
    assert client.get("/api/v1/analytics/history?lat=17.385&lon=78.4867&start=2026-10-01&end=2026-10-20").status_code == 400
    assert client.get("/api/v1/analytics/history?lat=17.385&lon=78.4867&start=bad").status_code == 422
    assert client.get("/api/v1/analytics/limits").json()["earliest"] == "2022-08-04"


def test_route_provider_down_returns_503(monkeypatch):
    def boom(url, params):
        raise RuntimeError("connection refused")
    monkeypatch.setattr(an, "_fetch", boom)
    monkeypatch.setattr(an, "today_ist", lambda: TODAY)
    monkeypatch.setattr("backend.api.routes.analytics.today_ist", lambda: TODAY)
    an._cache.clear()
    r = client.get("/api/v1/analytics/history?lat=17.385&lon=78.4867&start=2026-09-29&end=2026-10-01")
    assert r.status_code == 503 and r.json()["detail"]["status"] == "provider_unavailable"
