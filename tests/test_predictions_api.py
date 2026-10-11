"""Prediction service / API tests.

The inference frame is a REAL historical extract (Hyderabad, 28 Sep - 2 Oct
2026, CAMS + archived NWP forecast) replayed as if it were live, so these
tests need no network access.
"""
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.schemas.predictions import PredictionResponse
from backend.services import prediction_service as ps
from ml import config

client = TestClient(app)
SAMPLE = Path(config.SAMPLES) / "hyderabad_frame_2026-09-28_to_10-02.parquet"
MODELS_READY = (config.MODELS / "uv_model.joblib").exists() and (config.MODELS / "ozone_model.joblib").exists()
NOW = datetime(2026, 10, 1, 3, 20, tzinfo=timezone.utc)   # 08:50 IST
CELL = {"cams_cell": [17.4, 78.5], "nwp_cell": [17.39, 78.46], "elevation_m": 500.0}


def _frame():
    f = pd.read_parquet(SAMPLE)
    cols = [c for c in f.columns if c != "time_utc"]
    f[cols] = f[cols].astype(float)
    return f


def test_invalid_coordinates_rejected():
    assert client.get("/api/v1/predictions/24h?lat=40&lon=78").status_code == 400      # outside India
    assert client.get("/api/v1/predictions/24h?lat=100&lon=78").status_code == 422     # not a latitude
    assert client.get("/api/v1/predictions/24h?lat=abc&lon=78").status_code == 422


def test_provider_unavailable_returns_503(monkeypatch):
    if not MODELS_READY:
        pytest.skip("models not trained")
    def boom(lat, lon):
        raise ps.PredictionUnavailable("Open-Meteo down", "provider_unavailable")
    monkeypatch.setattr(ps, "fetch_live_frame", boom)
    ps._cache.clear()
    r = client.get("/api/v1/predictions/24h?lat=21.0&lon=79.0")
    assert r.status_code == 503
    assert r.json()["detail"]["status"] == "provider_unavailable"


def test_missing_models_returns_503(monkeypatch):
    def missing():
        raise ps.PredictionUnavailable("Model artifacts not found", "model_not_trained")
    monkeypatch.setattr("backend.api.routes.predictions.predict_24h", lambda lat, lon: missing())
    r = client.get("/api/v1/predictions/24h?lat=21.0&lon=79.0")
    assert r.status_code == 503 and r.json()["detail"]["status"] == "model_not_trained"


@pytest.mark.skipif(not MODELS_READY, reason="models not trained")
def test_model_loading():
    art = ps.load_artifacts()
    assert set(art["schema"]["ozone"]["features"]) <= set(art["ozone"].feature_name_ if hasattr(art["ozone"], "feature_name_") else art["schema"]["ozone"]["features"])
    assert art["meta"]["model_version"]


@pytest.mark.skipif(not MODELS_READY, reason="models not trained")
def test_24h_forecast_structure_and_physics():
    out = ps.predict_24h(17.385, 78.4867, now=NOW, frame=_frame(), cell_meta=CELL)
    PredictionResponse.model_validate(out)
    P = out["predictions"]
    assert [p["lead_hours"] for p in P] == list(range(1, 25))
    assert pd.Timestamp(P[0]["time_utc"]) == pd.Timestamp("2026-10-01T04:00Z")
    assert P[0]["time_ist"].endswith("+05:30")
    uv = np.array([p["uv"]["value"] for p in P])
    assert (uv >= 0).all()
    for p in P:
        if p["solar_elevation_deg"] < -1:
            assert p["uv"]["value"] == 0
        assert p["uv"]["lower"] <= p["uv"]["value"] <= p["uv"]["upper"]
        assert p["ozone"]["lower"] <= p["ozone"]["value"] <= p["ozone"]["upper"]
    assert out["peak_uv"]["value"] == pytest.approx(uv.max(), abs=0.01)
    assert out["prediction_quality"]["tier"] == "high"
    assert out["targets"]["ozone"]["unit"] == "µg/m³"


@pytest.mark.skipif(not MODELS_READY, reason="models not trained")
def test_inference_ignores_future_cams_values():
    f = _frame()
    a = ps.predict_24h(17.385, 78.4867, now=NOW, frame=f, cell_meta=CELL)
    g = f.copy()
    g.loc[g["time_utc"] > pd.Timestamp("2026-10-01T03:00Z"), ["cams_ozone", "cams_uv_index"]] = 999.0
    b = ps.predict_24h(17.385, 78.4867, now=NOW, frame=g, cell_meta=CELL)
    assert [p["uv"]["value"] for p in a["predictions"]] == [p["uv"]["value"] for p in b["predictions"]]
    assert [p["ozone"]["value"] for p in a["predictions"]] == [p["ozone"]["value"] for p in b["predictions"]]


@pytest.mark.skipif(not MODELS_READY, reason="models not trained")
def test_missing_weather_forecast_refuses(monkeypatch):
    f = _frame()
    f.loc[f["time_utc"] > pd.Timestamp("2026-10-01T03:00Z"), [c for c in f.columns if c.startswith("wx_")]] = np.nan
    with pytest.raises(ps.PredictionUnavailable):
        ps.predict_24h(17.385, 78.4867, now=NOW, frame=f, cell_meta=CELL)


@pytest.mark.skipif(not MODELS_READY, reason="models not trained")
def test_route_end_to_end_with_replayed_frame(monkeypatch):
    monkeypatch.setattr(ps, "fetch_live_frame", lambda lat, lon: (_frame(), CELL))
    real = ps.predict_24h
    monkeypatch.setattr("backend.api.routes.predictions.predict_24h", lambda lat, lon: real(lat, lon, now=NOW))
    ps._cache.clear()
    r = client.get("/api/v1/predictions/24h?lat=17.385&lon=78.4867")
    assert r.status_code == 200
    body = r.json()
    assert len(body["predictions"]) == 24 and body["peak_uv"]["risk"] in ["Low", "Moderate", "High", "Very High", "Extreme"]


@pytest.mark.skipif(not MODELS_READY, reason="models not trained")
def test_model_info_is_json_safe():
    """model_metadata.json stores XGBoost's `missing: NaN`; the route must still return valid JSON."""
    r = client.get("/api/v1/predictions/model-info")
    assert r.status_code == 200
    body = r.json()
    assert body["metadata"]["model_version"]
    assert body["metadata"]["models"]["ozone"]["hyperparameters"]["missing"] is None
    assert body["test"]["ozone"]["mae"] > 0 and body["test"]["uv"]["mae"] > 0


@pytest.mark.skipif(not (config.MODELS / "ozone_model.json").exists(), reason="portable model files not present")
def test_models_load_without_pickle(monkeypatch):
    """Serving must work from the portable XGBoost JSON files even where the .joblib
    pickles cannot be opened (seen on Windows: 'XGBoostError: input stream corrupted')."""
    def broken(*a, **k):
        raise RuntimeError("input stream corrupted")
    monkeypatch.setattr(ps.joblib, "load", broken)
    ps.load_artifacts.cache_clear()
    try:
        out = ps.predict_24h(17.385, 78.4867, now=NOW, frame=_frame(), cell_meta=CELL)
        assert len(out["predictions"]) == 24
        assert out["model"]["ozone_algorithm"] == "XGBoost"
    finally:
        ps.load_artifacts.cache_clear()
