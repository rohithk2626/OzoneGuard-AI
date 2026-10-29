"""PAST: historical ozone / UV / weather for any point in India.

Real data only, fetched on demand for the exact coordinate:

  * CAMS global atmospheric composition (ECMWF/Copernicus) via the Open-Meteo
    Air Quality API  -> surface ozone (µg/m³), UV index, NO2, aerosol optical depth
  * archived NWP forecasts via the Open-Meteo Historical Forecast API
                      -> temperature, humidity, cloud, rain, wind, sunlight

These are the same two sources (and the same request shape) the training data was
collected with (ml/collect_data.py), so PAST, NOW and FUTURE agree with each other.
Hourly values are requested in UTC and grouped into Indian days (IST) here.
If a provider is down the caller gets an error -- nothing is invented.
"""
from __future__ import annotations

import threading
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

import numpy as np
import pandas as pd
import requests

from backend.core.errors import describe_failure
from ml.risk import RISK_LABELS, uv_risk_label

AQ_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
HF_URL = "https://historical-forecast-api.open-meteo.com/v1/forecast"
IST = timezone(timedelta(hours=5, minutes=30))

EARLIEST = date(2022, 8, 4)          # CAMS global via Open-Meteo starts here for India
MAX_DAYS = 366
MIN_HOURS_FOR_FULL_DAY = 20          # a day with fewer hours is flagged "partial"

AQ_VARS = ["ozone", "uv_index", "nitrogen_dioxide", "aerosol_optical_depth"]
WX_VARS = ["temperature_2m", "relative_humidity_2m", "cloud_cover", "precipitation",
           "wind_speed_10m", "shortwave_radiation"]



class AnalyticsUnavailable(RuntimeError):
    """Raised when real history cannot be produced. Nothing is fabricated."""

    def __init__(self, message: str, status: str = "provider_unavailable"):
        super().__init__(message)
        self.status = status


class InvalidRange(ValueError):
    """The requested date range is not usable."""


def today_ist() -> date:
    return datetime.now(IST).date()


def validate_range(start: date, end: date, today: date | None = None) -> None:
    today = today or today_ist()
    if start > end:
        raise InvalidRange("The start date must be on or before the end date.")
    if end > today:
        raise InvalidRange("The end date cannot be in the future.")
    if start < EARLIEST:
        raise InvalidRange(f"History is available from {EARLIEST.isoformat()} onwards.")
    if (end - start).days + 1 > MAX_DAYS:
        raise InvalidRange(f"Choose a range of at most {MAX_DAYS} days.")


def uv_risk(value: float | None) -> str | None:
    """WHO UV category (same rounding rule as the Predictions page: ml/risk.py)."""
    if value is None or not np.isfinite(value):
        return None
    return uv_risk_label(float(value))


# --------------------------------------------------------------------------- fetch
def _fetch(url: str, params: dict) -> dict:
    r = requests.get(url, params=params, timeout=60)
    r.raise_for_status()
    payload = r.json()
    if payload.get("error"):
        raise RuntimeError(payload.get("reason"))
    return payload


def fetch_hourly(lat: float, lon: float, start: date, end: date) -> tuple[pd.DataFrame, dict]:
    """Hourly frame indexed by UTC time. One extra day each side covers the IST offset."""
    s, e = (start - timedelta(days=1)).isoformat(), (end + timedelta(days=1)).isoformat()
    try:
        aq = _fetch(AQ_URL, {"latitude": lat, "longitude": lon, "hourly": ",".join(AQ_VARS),
                             "start_date": s, "end_date": e, "timezone": "GMT", "domains": "cams_global"})
    except Exception as exc:
        raise AnalyticsUnavailable(f"CAMS composition history unavailable from Open-Meteo: {describe_failure(exc)}.")
    try:
        wx = _fetch(HF_URL, {"latitude": lat, "longitude": lon, "hourly": ",".join(WX_VARS),
                             "start_date": s, "end_date": e, "timezone": "GMT"})
    except Exception as exc:
        raise AnalyticsUnavailable(f"Weather history unavailable from Open-Meteo: {describe_failure(exc)}.")
    df = pd.DataFrame(aq["hourly"]).merge(pd.DataFrame(wx["hourly"]), on="time", how="outer")
    df["time_utc"] = pd.to_datetime(df.pop("time"), utc=True)
    meta = {"cams_cell": [aq.get("latitude"), aq.get("longitude")],
            "weather_cell": [wx.get("latitude"), wx.get("longitude")], "elevation_m": wx.get("elevation")}
    return df.sort_values("time_utc").reset_index(drop=True), meta


# --------------------------------------------------------------------------- maths
def _r(x: Any, n: int = 1) -> float | None:
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return round(x, n) if np.isfinite(x) else None


def _corr(a: pd.Series, b: pd.Series) -> dict[str, Any]:
    ok = a.notna() & b.notna()
    n = int(ok.sum())
    if n < 24 or a[ok].std() == 0 or b[ok].std() == 0:
        return {"r": None, "n": n}
    return {"r": _r(a[ok].corr(b[ok]), 2), "n": n}


def summarise(df: pd.DataFrame, start: date, end: date, now: datetime | None = None) -> dict:
    """Turn an hourly UTC frame into daily rows (IST days), an average day and summary numbers."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cols = AQ_VARS + WX_VARS
    df = df.copy()
    for c in cols:
        df[c] = pd.to_numeric(df[c], errors="coerce") if c in df else np.nan
    df = df[df["time_utc"] <= pd.Timestamp(now)]            # never report hours that have not happened
    local = df["time_utc"].dt.tz_convert(IST)
    df["day"] = local.dt.date
    df["hour"] = local.dt.hour
    df = df[(df["day"] >= start) & (df["day"] <= end)]
    if df.empty or df[["ozone", "uv_index"]].notna().sum().sum() == 0:
        raise AnalyticsUnavailable("The data providers returned no values for this place and period.", "no_data")

    g = df.groupby("day")
    daily = pd.DataFrame({
        "hours": g["ozone"].count(),
        "ozone_mean": g["ozone"].mean(), "ozone_max": g["ozone"].max(),
        "uv_max": g["uv_index"].max(),
        "no2_mean": g["nitrogen_dioxide"].mean(), "aod_mean": g["aerosol_optical_depth"].mean(),
        "temp_mean": g["temperature_2m"].mean(), "temp_min": g["temperature_2m"].min(), "temp_max": g["temperature_2m"].max(),
        "humidity_mean": g["relative_humidity_2m"].mean(), "cloud_mean": g["cloud_cover"].mean(),
        "precip_sum": g["precipitation"].sum(min_count=1), "wind_mean": g["wind_speed_10m"].mean(),
        "sunlight_mean": g["shortwave_radiation"].mean(),
    }).reset_index()

    rows = []
    for d in daily.itertuples():
        rows.append({
            "date": d.day.isoformat(), "hours": int(d.hours), "partial": bool(d.hours < MIN_HOURS_FOR_FULL_DAY),
            "ozone_mean": _r(d.ozone_mean), "ozone_max": _r(d.ozone_max),
            "uv_max": _r(d.uv_max, 2), "uv_risk": uv_risk(d.uv_max),
            "no2_mean": _r(d.no2_mean), "aod_mean": _r(d.aod_mean, 2),
            "temp_mean": _r(d.temp_mean), "temp_min": _r(d.temp_min), "temp_max": _r(d.temp_max),
            "humidity_mean": _r(d.humidity_mean, 0), "cloud_mean": _r(d.cloud_mean, 0),
            "precip_sum": _r(d.precip_sum), "wind_mean": _r(d.wind_mean), "sunlight_mean": _r(d.sunlight_mean, 0),
        })

    h = df.groupby("hour")
    diurnal = [{"hour_ist": int(k), "ozone": _r(v["ozone"].mean()), "uv": _r(v["uv_index"].mean(), 2),
                "temp": _r(v["temperature_2m"].mean())} for k, v in h]

    full = daily[daily["hours"] >= MIN_HOURS_FOR_FULL_DAY]
    basis = full if len(full) else daily

    def peak(col: str) -> dict[str, Any] | None:
        if basis[col].notna().sum() == 0:
            return None
        i = basis[col].idxmax()
        return {"value": _r(basis.loc[i, col], 2), "date": basis.loc[i, "day"].isoformat()}

    risk_days = {label: 0 for label in RISK_LABELS}
    for v in basis["uv_max"].dropna():
        risk_days[uv_risk(v)] += 1

    day_rows = df[df["shortwave_radiation"] > 20]             # daylight hours, for the relationships
    summary = {
        "days": int(len(daily)), "full_days": int(len(full)), "hours": int(len(df)),
        "ozone_mean": _r(df["ozone"].mean()), "ozone_min": _r(df["ozone"].min()), "ozone_max": _r(df["ozone"].max()),
        "uv_daily_max_mean": _r(basis["uv_max"].mean(), 2),
        "highest_uv": peak("uv_max"), "highest_ozone_day": peak("ozone_mean"),
        "temp_mean": _r(df["temperature_2m"].mean()), "humidity_mean": _r(df["relative_humidity_2m"].mean(), 0),
        "cloud_mean": _r(df["cloud_cover"].mean(), 0), "precip_total": _r(df["precipitation"].sum(min_count=1)),
        "uv_risk_days": risk_days,
    }
    relationships = {
        "basis": "hourly values in daylight hours (sunlight above 20 W/m²) for the selected period",
        "ozone_vs_uv": _corr(day_rows["ozone"], day_rows["uv_index"]),
        "ozone_vs_temperature": _corr(day_rows["ozone"], day_rows["temperature_2m"]),
        "ozone_vs_humidity": _corr(day_rows["ozone"], day_rows["relative_humidity_2m"]),
        "ozone_vs_sunlight": _corr(day_rows["ozone"], day_rows["shortwave_radiation"]),
        "uv_vs_cloud": _corr(day_rows["uv_index"], day_rows["cloud_cover"]),
        "note": "Correlation is not cause. Ozone and UV move together mainly because both follow the sun.",
    }
    return {"daily": rows, "average_day": diurnal, "summary": summary, "relationships": relationships}


# --------------------------------------------------------------------------- entry
_cache: dict[tuple, tuple[float, dict]] = {}
_lock = threading.Lock()
_CACHE_MAX = 64


def get_history(lat: float, lon: float, start: date, end: date) -> dict:
    validate_range(start, end)
    key = (round(lat, 2), round(lon, 2), start, end)
    ttl = 900 if end >= today_ist() - timedelta(days=1) else 6 * 3600     # recent ranges still change
    with _lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
    frame, meta = fetch_hourly(lat, lon, start, end)
    out = summarise(frame, start, end)
    result = {
        "location": {"latitude": lat, "longitude": lon, **meta},
        "period": {"start": start.isoformat(), "end": end.isoformat(), "timezone": "Asia/Kolkata (IST, UTC+5:30)"},
        "generated_at": datetime.now(timezone.utc).isoformat(),
        **out,
        "units": {"ozone": "µg/m³ (ground-level ozone)", "uv": "UV index (WHO scale)", "no2": "µg/m³",
                  "aod": "aerosol optical depth (no unit)", "temperature": "°C", "humidity": "%", "cloud": "%",
                  "precipitation": "mm", "wind": "km/h", "sunlight": "W/m²"},
        "data_status": {
            "note": "Ozone and UV are CAMS model analyses/forecasts, not ground-sensor readings. "
                    "Weather is the archived forecast for each hour. Each value is for the nearest grid cell.",
            "sources": [
                {"name": "CAMS via Open-Meteo Air Quality API", "purpose": "Ground-level ozone, UV index, NO₂, haze", "status": "live"},
                {"name": "Open-Meteo Historical Forecast API", "purpose": "Temperature, humidity, cloud, rain, wind, sunlight", "status": "live"},
            ],
        },
    }
    with _lock:
        if len(_cache) >= _CACHE_MAX:
            _cache.pop(min(_cache, key=lambda k: _cache[k][0]))
        _cache[key] = (time.time(), result)
    return result
