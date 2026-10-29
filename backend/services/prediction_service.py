"""FUTURE: 24-hour ozone / UV prediction service.

Live inference path (mirrors training exactly through ml.features.build_rows):

  user lat/lon
    -> Open-Meteo Air Quality API (CAMS)  : recent surface O3 / UV / NO2 / AOD up to the issue hour
    -> Open-Meteo Forecast API (best_match): weather forecast for the next 24 h
    -> NOAA solar geometry                : computed
    -> ml.features.build_rows             : identical feature code as training
    -> ozone model -> UV model            : one of two interchangeable model families
                                            * "xgboost" (default): direct multi-horizon XGBoost, models/xgboost/
                                            * "lstm": encoder-decoder LSTM (NumPy forward pass), models/lstm/
                                            chosen per request (?model=) or by env OZONEGUARD_MODEL
    -> split-conformal 90 % intervals, WHO UV risk, peak UV, high-risk window

CAMS values AFTER the issue hour are discarded before feature building so no
future composition values can enter the features.
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any

import joblib
import numpy as np
import pandas as pd
import requests

from backend.core.errors import describe_failure
from ml import config
from ml.features import build_rows
from ml.lstm import NumpyLSTMForecaster, forecast_frame
from ml.quality import quality_tier
from ml.risk import RISK_LABELS, uv_risk_index, uv_risk_label

AQ_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
FC_URL = "https://api.open-meteo.com/v1/forecast"
IST = timezone(timedelta(hours=5, minutes=30))
CACHE_SECONDS = 600


class PredictionUnavailable(RuntimeError):
    """Raised when real predictions cannot be produced. Nothing is fabricated."""

    def __init__(self, message: str, status: str = "unavailable"):
        super().__init__(message)
        self.status = status


# ------------------------------------------------------------------------- artifacts
MODEL_NAMES = tuple(config.MODEL_DIRS)


def resolve_model(name: str | None = None) -> str:
    """Request value -> env OZONEGUARD_MODEL -> config.DEFAULT_MODEL."""
    name = (name or os.environ.get("OZONEGUARD_MODEL") or config.DEFAULT_MODEL).strip().lower()
    if name not in config.MODEL_DIRS:
        raise PredictionUnavailable(f"Unknown model '{name}'. Choose one of: {', '.join(MODEL_NAMES)}.",
                                    status="unknown_model")
    return name


def _load_model(target: str, model_dir=config.MODELS_XGBOOST):
    """Load one trained model.

    Prefers XGBoost's native JSON file (<target>_model.json), which is portable across
    operating systems, Python versions and XGBoost versions. The .joblib file is a pickle
    of XGBoost's internal memory snapshot and can fail to open on a different machine
    ("XGBoostError: input stream corrupted"), so it is only the fallback.
    """
    native = model_dir / f"{target}_model.json"
    if native.exists():
        from xgboost import XGBRegressor
        model = XGBRegressor()
        model.load_model(native)
        return model
    return joblib.load(model_dir / f"{target}_model.joblib")


@lru_cache(maxsize=len(config.MODEL_DIRS))
def load_artifacts(model: str | None = None) -> dict[str, Any]:
    name = resolve_model(model)
    m = config.MODEL_DIRS[name]
    needed = ["feature_schema.json", "conformal.json", "model_metadata.json"]
    if name == "lstm":
        needed += ["lstm_weights.npz", "lstm_config.json"]
    missing = [n for n in needed if not (m / n).exists()]
    if name == "xgboost":
        missing += [f"{t}_model.json or {t}_model.joblib" for t in ("ozone", "uv")
                    if not (m / f"{t}_model.json").exists() and not (m / f"{t}_model.joblib").exists()]
    if missing:
        cmd = "python -m ml.train_lstm" if name == "lstm" else "python -m ml.train_xgboost"
        raise PredictionUnavailable(
            f"{name} model artifacts not found in {m.relative_to(config.ROOT)} ({', '.join(missing)}). Run: {cmd}",
            status="model_not_trained")
    metrics = json.loads((m / "metrics.json").read_text()) if (m / "metrics.json").exists() else {}
    clim_path = config.MODELS / "climatology.parquet"
    clim = pd.read_parquet(clim_path) if clim_path.exists() else None
    if name == "lstm":
        net = NumpyLSTMForecaster(m)
        models = {"lstm": net, "ozone": net, "uv": net}
    else:
        models = {"ozone": _load_model("ozone", m), "uv": _load_model("uv", m)}
    return {
        "name": name,
        **models,
        "schema": json.loads((m / "feature_schema.json").read_text()),
        "conformal": json.loads((m / "conformal.json").read_text()),
        "meta": json.loads((m / "model_metadata.json").read_text()),
        "metrics": metrics,
        "climatology": clim,
    }


# ------------------------------------------------------------------------- live data
def _fetch(url: str, params: dict) -> dict:
    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()
    payload = r.json()
    if payload.get("error"):
        raise RuntimeError(payload.get("reason"))
    return payload


def fetch_live_frame(lat: float, lon: float) -> tuple[pd.DataFrame, dict]:
    try:
        aq = _fetch(AQ_URL, {"latitude": lat, "longitude": lon, "hourly": ",".join(config.CAMS_VARS),
                             "past_days": 3, "forecast_days": 2, "timezone": "GMT", "domains": "cams_global"})
    except Exception as exc:
        raise PredictionUnavailable(f"CAMS composition data unavailable from Open-Meteo: {describe_failure(exc)}.", "provider_unavailable")
    try:
        wx = _fetch(FC_URL, {"latitude": lat, "longitude": lon, "hourly": ",".join(config.WX_VARS),
                             "past_days": 3, "forecast_days": 3, "timezone": "GMT"})
    except Exception as exc:
        raise PredictionUnavailable(f"Weather forecast unavailable from Open-Meteo: {describe_failure(exc)}.", "provider_unavailable")
    a = pd.DataFrame(aq["hourly"]).rename(columns={v: f"cams_{v}" for v in config.CAMS_VARS})
    w = pd.DataFrame(wx["hourly"]).rename(columns={v: f"wx_{v}" for v in config.WX_VARS})
    df = a.merge(w, on="time", how="outer")
    df["time_utc"] = pd.to_datetime(df.pop("time"), utc=True)
    meta = {"cams_cell": [aq.get("latitude"), aq.get("longitude")], "nwp_cell": [wx.get("latitude"), wx.get("longitude")],
            "elevation_m": wx.get("elevation")}
    return df.sort_values("time_utc").reset_index(drop=True), meta


# ------------------------------------------------------------------------- helpers
def _conformal(conf: dict, target: str, lead: np.ndarray, pred: np.ndarray):
    edges = conf["value_edges"]
    out_lo, out_hi = [], []
    for h, p in zip(lead, pred):
        lb = next((f"{a}-{b}" for a, b in conf["lead_bins"] if a <= h <= b), "13-24")
        vb = int(np.clip(np.digitize([p], edges)[0] - 1, 0, len(edges) - 2))
        q = conf["bins"].get(f"lead{lb}|v{vb}", {"q": conf["global_q"]})["q"]
        out_lo.append(max(p - q, 0.0))
        out_hi.append(p + q)
    return np.array(out_lo), np.array(out_hi)


def _climatology(art: dict, lat: float, lon: float):
    clim = art["climatology"]
    if clim is None:
        return None, None
    locs = clim.groupby("location_id")[["req_lat", "req_lon"]].first()
    from ml.quality import _hav
    d = locs.apply(lambda r: _hav(lat, lon, r.req_lat, r.req_lon), axis=1)
    if d.min() > 50:
        return None, None
    lid = d.idxmin()
    return clim[clim["location_id"] == lid], lid


def _windows(times: list[pd.Timestamp], flags: np.ndarray) -> list[dict]:
    out, start = [], None
    for i, f in enumerate(flags):
        if f and start is None:
            start = i
        if (not f or i == len(flags) - 1) and start is not None:
            end = i if f else i - 1
            out.append({"start_utc": times[start].isoformat(), "end_utc": (times[end] + pd.Timedelta(hours=1)).isoformat(),
                        "start_ist": times[start].tz_convert(IST).isoformat(),
                        "end_ist": (times[end] + pd.Timedelta(hours=1)).tz_convert(IST).isoformat(), "hours": end - start + 1})
            start = None
    return out


def _r(x, n=2):
    return None if x is None or not np.isfinite(x) else round(float(x), n)


# ------------------------------------------------------------------------- main entry
_cache: dict[tuple, tuple[float, dict]] = {}
_lock = threading.Lock()


def predict_24h(lat: float, lon: float, now: datetime | None = None, frame: pd.DataFrame | None = None,
                cell_meta: dict | None = None, model: str | None = None) -> dict:
    model = resolve_model(model)
    art = load_artifacts(model)
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    issue = pd.Timestamp(now).floor("h")
    key = (round(lat, 2), round(lon, 2), issue, model)
    if frame is None:
        with _lock:
            hit = _cache.get(key)
            if hit and time.time() - hit[0] < CACHE_SECONDS:
                return hit[1]
        frame, cell_meta = fetch_live_frame(lat, lon)
    cell_meta = cell_meta or {}

    # ---- enforce the information set: no CAMS value after the issue hour ----
    frame = frame.copy()
    cams_cols = [c for c in frame.columns if c.startswith("cams_")]
    value_cols = [c for c in frame.columns if c.startswith(("cams_", "wx_"))]
    frame[value_cols] = frame[value_cols].astype(float)
    reference = frame[frame["time_utc"] > issue][["time_utc", "cams_ozone", "cams_uv_index"]].copy()
    frame.loc[frame["time_utc"] > issue, cams_cols] = np.nan
    frame = frame[frame["time_utc"] <= issue + pd.Timedelta(hours=24)]

    rows = build_rows(frame, [issue], lat, lon, cell_meta.get("elevation_m"), include_targets=False)
    if len(rows) < 24:
        raise PredictionUnavailable(f"Only {len(rows)} of 24 forecast hours could be built from provider data.")
    rows = rows.sort_values("lead_h").reset_index(drop=True)

    wx_needed = ["fc_temperature_2m", "fc_cloud_cover", "fc_uv_index"]
    if rows[wx_needed].isna().all(axis=None):
        raise PredictionUnavailable("Weather forecast fields are empty; refusing to predict without them.")
    status_notes = []
    for c in ["ozone_t", "uv_t"]:
        if rows[c].isna().any():
            status_notes.append(f"latest CAMS value missing for {c[:-2]}; model used remaining features")

    so = art["schema"]
    if model == "lstm":
        try:
            seq = forecast_frame(art["lstm"], frame, issue, lat, lon, cell_meta.get("elevation_m"))
        except ValueError as exc:
            raise PredictionUnavailable(f"LSTM input window incomplete: {exc}")
        seq = seq.set_index("target_time").reindex(rows["target_time"])
        oz_pred = np.maximum(seq["pred_ozone"].to_numpy(dtype=float), 0.0)
        uv_pred = np.maximum(seq["pred_uv"].to_numpy(dtype=float), 0.0)
        if not (np.isfinite(oz_pred).all() and np.isfinite(uv_pred).all()):
            raise PredictionUnavailable("LSTM produced no value for some forecast hours.")
        rows["pred_ozone"] = oz_pred
    else:
        oz_pred = np.maximum(art["ozone"].predict(rows[so["ozone"]["features"]]), 0.0)
        rows["pred_ozone"] = oz_pred
        uv_pred = np.maximum(art["uv"].predict(rows[so["uv"]["features"]]), 0.0)
    uv_pred = np.where(rows["solar_elevation"].to_numpy() < -1.0, 0.0, uv_pred)
    lead = rows["lead_h"].to_numpy()
    oz_lo, oz_hi = _conformal(art["conformal"]["ozone"], "ozone", lead, oz_pred)
    uv_lo, uv_hi = _conformal(art["conformal"]["uv"], "uv", lead, uv_pred)
    uv_lo = np.where(rows["solar_elevation"].to_numpy() < -1.0, 0.0, uv_lo)
    uv_hi = np.where(rows["solar_elevation"].to_numpy() < -1.0, 0.0, uv_hi)

    clim, clim_loc = _climatology(art, lat, lon)
    times = list(rows["target_time"])
    hours = []
    for i, T in enumerate(times):
        anomaly = None
        if clim is not None:
            c = clim[(clim["month"] == T.month) & (clim["hour"] == T.hour)]
            if len(c) and c["ozone_std"].iloc[0] > 0:
                mu, sd = float(c["ozone_mean"].iloc[0]), float(c["ozone_std"].iloc[0])
                anomaly = {"absolute": _r(oz_pred[i] - mu), "standardized": _r((oz_pred[i] - mu) / sd),
                           "climatology_mean": _r(mu), "climatology_std": _r(sd)}
        hours.append({
            "lead_hours": int(lead[i]),
            "time_utc": T.isoformat(),
            "time_ist": T.tz_convert(IST).isoformat(),
            "ozone": {"value": _r(oz_pred[i], 1), "lower": _r(oz_lo[i], 1), "upper": _r(oz_hi[i], 1), "anomaly": anomaly},
            "uv": {"value": _r(uv_pred[i], 2), "lower": _r(uv_lo[i], 2), "upper": _r(uv_hi[i], 2),
                   "risk": uv_risk_label(uv_pred[i]), "risk_level": int(uv_risk_index([uv_pred[i]])[0])},
            "solar_elevation_deg": _r(rows.loc[i, "solar_elevation"], 1),
            "weather": {"temperature_c": _r(rows.loc[i, "fc_temperature_2m"], 1),
                        "relative_humidity_pct": _r(rows.loc[i, "fc_relative_humidity_2m"], 0),
                        "cloud_cover_pct": _r(rows.loc[i, "fc_cloud_cover"], 0),
                        "precipitation_mm": _r(rows.loc[i, "fc_precipitation"], 1),
                        "wind_speed_kmh": _r(rows.loc[i, "fc_wind_speed_10m"], 1),
                        "shortwave_radiation_wm2": _r(rows.loc[i, "fc_shortwave_radiation"], 0)},
        })

    pk = int(np.argmax(uv_pred))
    high_flags = uv_risk_index(uv_pred) >= 2
    upper_flags = uv_risk_index(uv_hi) >= 2
    quality, dist_km = quality_tier(lat, lon)
    meta = art["meta"]
    m = art["metrics"]
    evidence = {}
    if m:
        evidence = {
            "test_mae_seen_locations": {"ozone": _r(m["test"]["ozone"]["model"]["mae"]), "uv": _r(m["test"]["uv"]["model"]["mae"])},
            "test_mae_unseen_holdout_locations": {"ozone": _r(m["spatial_holdout_test"]["ozone"]["model"]["mae"]),
                                                  "uv": _r(m["spatial_holdout_test"]["uv"]["model"]["mae"])},
            "interval_coverage_test": {"ozone": _r(m["test"]["ozone"]["interval_90"]["coverage"], 3),
                                       "uv": _r(m["test"]["uv"]["interval_90"]["coverage"], 3)},
        }
    explanation = {
        "high": "Within 50 km of a training location: test-period accuracy applies.",
        "medium": "50–350 km from the nearest training location: accuracy measured on held-out (never-trained) locations applies.",
        "low": "More than 350 km from any training location: accuracy NOT VERIFIED for this area.",
    }[quality]
    result = {
        "location": {"latitude": lat, "longitude": lon, "cams_cell": cell_meta.get("cams_cell"),
                     "nwp_cell": cell_meta.get("nwp_cell"), "elevation_m": cell_meta.get("elevation_m")},
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "issue_time_utc": issue.isoformat(),
        "issue_time_ist": issue.tz_convert(IST).isoformat(),
        "horizon_hours": 24,
        "predictions": hours,
        "peak_uv": {"value": _r(uv_pred[pk], 2), "lower": _r(uv_lo[pk], 2), "upper": _r(uv_hi[pk], 2),
                    "time_utc": times[pk].isoformat(), "time_ist": times[pk].tz_convert(IST).isoformat(),
                    "risk": uv_risk_label(uv_pred[pk])},
        "high_risk_windows": _windows(times, high_flags),
        "possible_high_risk_windows_upper_bound": _windows(times, upper_flags),
        "summary": {"max_ozone": _r(float(oz_pred.max()), 1), "min_ozone": _r(float(oz_pred.min()), 1),
                    "max_risk": RISK_LABELS[int(uv_risk_index([uv_pred.max()])[0])]},
        "targets": {
            "ozone": {"quantity": "Surface (ground-level) ozone mass concentration", "unit": "µg/m³",
                      "truth_source": "CAMS global atmospheric composition (ECMWF/Copernicus) via Open-Meteo",
                      "note": "Not total-column ozone (Dobson Units). The Location page shows NASA total-column ozone separately."},
            "uv": {"quantity": "All-sky UV index", "unit": "UV index (WHO scale)",
                   "truth_source": "CAMS UV index via Open-Meteo (model-derived; no public ground UV network for India)"},
        },
        "uncertainty": {"method": "Split-conformal prediction (Mondrian by lead time and predicted level), calibrated on Oct 2024–Sep 2025",
                        "nominal_coverage": 0.9,
                        "meaning": "Ranges are built so that ~90 % of past outcomes fell inside them for similar lead times and levels. "
                                   "They are empirical ranges, not a guarantee and not a 'confidence' score."},
        "prediction_quality": {"tier": quality, "distance_to_nearest_training_point_km": _r(dist_km, 1),
                               "explanation": explanation, "evidence": evidence},
        "model": {"name": model, "version": meta.get("model_version"), "dataset_version": meta.get("dataset_version"),
                  "ozone_algorithm": meta["models"]["ozone"]["algorithm"], "uv_algorithm": meta["models"]["uv"]["algorithm"],
                  "uv_uses_predicted_ozone": bool(so["uv"].get("uses_predicted_ozone")),
                  "trained_at": meta.get("trained_at")},
        "data_status": {
            "composition": "live", "weather_forecast": "live", "notes": status_notes,
            "anomaly": (f"standardized vs train-period climatology of '{clim_loc}'" if clim_loc
                        else "unavailable: no climatology within 50 km (only computed at training points)"),
            "sources": [
                {"name": "CAMS via Open-Meteo Air Quality API", "purpose": "Recent surface ozone, UV, NO₂, AOD (inputs up to issue hour)", "status": "live"},
                {"name": "Open-Meteo Forecast API (best_match)", "purpose": "Weather forecast for the next 24 h", "status": "live"},
                {"name": "NOAA solar position equations", "purpose": "Solar elevation / zenith", "status": "computed"},
            ],
        },
        "reference_cams_raw_forecast": [
            {"time_utc": r.time_utc.isoformat(), "ozone": _r(r.cams_ozone, 1), "uv": _r(r.cams_uv_index, 2)}
            for r in reference.head(24).itertuples()
        ],
    }
    with _lock:
        _cache[key] = (time.time(), result)
    return result
