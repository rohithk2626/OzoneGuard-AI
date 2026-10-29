"""LSTM model: input construction, information set, NumPy serving path, API selection."""
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
from ml import lstm as L

client = TestClient(app)
SAMPLE = Path(config.SAMPLES) / "hyderabad_frame_2026-09-28_to_10-02.parquet"
NOW = datetime(2026, 10, 1, 3, 20, tzinfo=timezone.utc)
CELL = {"cams_cell": [17.4, 78.5], "nwp_cell": [17.39, 78.46], "elevation_m": 500.0}
LSTM_READY = (config.MODELS_LSTM / "lstm_weights.npz").exists()


def _frame():
    f = pd.read_parquet(SAMPLE)
    cols = [c for c in f.columns if c != "time_utc"]
    f[cols] = f[cols].astype(float)
    return f


def test_decoder_never_sees_composition():
    assert not [c for c in L.DEC_FEATURES if c.startswith("cams_")]
    assert {"cams_ozone", "cams_uv_index"} <= set(L.ENC_FEATURES)


def test_windows_end_at_issue_hour():
    n = 100
    enc = np.arange(n, dtype=np.float32)[:, None].repeat(len(L.ENC_FEATURES), 1)
    dec = np.arange(n, dtype=np.float32)[:, None].repeat(len(L.DEC_FEATURES) - 1, 1)
    E, D = L.encoder_decoder_windows(enc, dec, np.array([60]))
    assert E.shape == (1, L.ENC_LEN, len(L.ENC_FEATURES)) and D.shape == (1, L.DEC_LEN, len(L.DEC_FEATURES))
    assert E[0, -1, 0] == 60 and E[0, 0, 0] == 60 - L.ENC_LEN + 1       # history t-47 .. t
    assert D[0, 0, 0] == 61 and D[0, -1, 0] == 60 + L.DEC_LEN            # forecast t+1 .. t+24
    assert D[0, -1, -1] == pytest.approx(1.0)                              # lead fraction


def test_numpy_lstm_layer_matches_reference_cell():
    """One step of the NumPy layer equals the textbook LSTM equations (PyTorch gate order i, f, g, o)."""
    rng = np.random.default_rng(0)
    F, H = 3, 4
    W_ih, W_hh, b = rng.normal(size=(4 * H, F)), rng.normal(size=(4 * H, H)), rng.normal(size=4 * H)
    x, h0, c0 = rng.normal(size=(1, 1, F)), rng.normal(size=(1, H)), rng.normal(size=(1, H))
    out, h, c = L._lstm_layer(x, W_ih, W_hh, b, h0, c0)
    g = W_ih @ x[0, 0] + W_hh @ h0[0] + b
    sig = lambda v: 1 / (1 + np.exp(-v))
    i, f, gg, o = sig(g[:H]), sig(g[H:2 * H]), np.tanh(g[2 * H:3 * H]), sig(g[3 * H:])
    c_ref = f * c0[0] + i * gg
    assert np.allclose(c[0], c_ref) and np.allclose(h[0], o * np.tanh(c_ref)) and np.allclose(out[0, 0], h[0])


def test_unknown_model_rejected():
    assert client.get("/api/v1/predictions/24h?lat=17.4&lon=78.5&model=prophet").status_code == 422
    with pytest.raises(ps.PredictionUnavailable):
        ps.resolve_model("prophet")


def test_models_endpoint_lists_both():
    r = client.get("/api/v1/predictions/models")
    assert r.status_code == 200
    body = r.json()
    assert set(body["models"]) == {"xgboost", "lstm"} and body["default"] in body["models"]


@pytest.mark.skipif(not LSTM_READY, reason="LSTM not trained")
def test_lstm_forecast_structure_and_physics():
    out = ps.predict_24h(17.385, 78.4867, now=NOW, frame=_frame(), cell_meta=CELL, model="lstm")
    PredictionResponse.model_validate(out)
    assert out["model"]["name"] == "lstm" and out["model"]["ozone_algorithm"] == "LSTM"
    P = out["predictions"]
    assert [p["lead_hours"] for p in P] == list(range(1, 25))
    for p in P:
        if p["solar_elevation_deg"] < -1:
            assert p["uv"]["value"] == 0
        assert p["uv"]["lower"] <= p["uv"]["value"] <= p["uv"]["upper"]
        assert p["ozone"]["lower"] <= p["ozone"]["value"] <= p["ozone"]["upper"]


@pytest.mark.skipif(not LSTM_READY, reason="LSTM not trained")
def test_lstm_ignores_future_cams_values():
    f = _frame()
    a = ps.predict_24h(17.385, 78.4867, now=NOW, frame=f, cell_meta=CELL, model="lstm")
    g = f.copy()
    g.loc[g["time_utc"] > pd.Timestamp("2026-10-01T03:00Z"), ["cams_ozone", "cams_uv_index"]] = 999.0
    b = ps.predict_24h(17.385, 78.4867, now=NOW, frame=g, cell_meta=CELL, model="lstm")
    assert [p["ozone"]["value"] for p in a["predictions"]] == [p["ozone"]["value"] for p in b["predictions"]]
    assert [p["uv"]["value"] for p in a["predictions"]] == [p["uv"]["value"] for p in b["predictions"]]


@pytest.mark.skipif(not LSTM_READY, reason="LSTM not trained")
def test_route_selects_model(monkeypatch):
    monkeypatch.setattr(ps, "fetch_live_frame", lambda lat, lon, **kw: (_frame(), CELL))
    real = ps.predict_24h
    monkeypatch.setattr("backend.api.routes.predictions.predict_24h", lambda lat, lon, **kw: real(lat, lon, now=NOW, **kw))
    ps._cache.clear()
    a = client.get("/api/v1/predictions/24h?lat=17.385&lon=78.4867&model=lstm").json()
    b = client.get("/api/v1/predictions/24h?lat=17.385&lon=78.4867&model=xgboost").json()
    assert a["model"]["name"] == "lstm" and b["model"]["name"] == "xgboost"
    assert client.get("/api/v1/predictions/model-info?model=lstm").json()["model"] == "lstm"
