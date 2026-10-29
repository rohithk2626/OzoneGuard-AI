"""LSTM forecaster: shared sequence building + a NumPy forward pass for serving.

Formulation (encoder-decoder, sequence-to-sequence, 24 h ahead in one pass)
-------------------------------------------------------------------------
* Encoder: an LSTM reads the last ``ENC_LEN`` hours up to and INCLUDING the
  issue hour t (CAMS composition, archived/live weather, solar geometry).
* Decoder: a second LSTM steps through the 24 target hours T = t+1 .. t+24,
  starting from the encoder state, and sees only things known in advance at
  t: the weather FORECAST for T, solar geometry and the calendar.
* A linear head turns every decoder step into (ozone, UV) for that hour.

Information-set rule (same as the XGBoost pipeline, see ml/features.py):
CAMS values are used only at times <= t; weather at T comes from a forecast.

The same ``build_hourly_matrix`` + ``encoder_decoder_windows`` code builds the
inputs for training (ml/train_lstm.py) and for live inference
(backend/services/prediction_service.py). Training uses PyTorch; serving uses
``NumpyLSTMForecaster`` below, which reproduces the PyTorch forward pass with
NumPy only, so the website does not need PyTorch installed.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from ml import config
from ml.solar import solar_position

ENC_LEN = 48          # hours of history the encoder reads (t-47 .. t)
DEC_LEN = 24          # forecast hours (t+1 .. t+24)
TARGET_COLS = ["cams_ozone", "cams_uv_index"]   # output order: ozone, uv

# CAMS composition: only ever read at times <= t (encoder only)
CAMS_IN = ["cams_ozone", "cams_uv_index", "cams_uv_index_clear_sky", "cams_nitrogen_dioxide",
           "cams_aerosol_optical_depth"]
# Weather (archived forecasts in training, live forecast at inference)
WX_IN = ["wx_temperature_2m", "wx_relative_humidity_2m", "wx_dew_point_2m", "wx_surface_pressure",
         "wx_cloud_cover", "wx_precipitation", "wx_shortwave_radiation", "wx_wind_speed_10m",
         "wx_wind_dir_sin", "wx_wind_dir_cos", "wx_uv_index", "wx_uv_index_clear_sky"]
# Deterministic: solar geometry + calendar
GEO_IN = ["solar_elevation", "cos_zenith", "sin_solar_time", "cos_solar_time", "sin_doy", "cos_doy",
          "earth_sun_distance_au", "daylight_hours"]
STATIC_IN = ["lat", "lon", "elevation_m"]

ENC_FEATURES = CAMS_IN + [f"{c}_missing" for c in ("cams_ozone", "cams_uv_index")] + WX_IN + GEO_IN + STATIC_IN
DEC_FEATURES = WX_IN + GEO_IN + STATIC_IN + ["lead_frac"]

# Columns that are standardised with train-period mean/std (flags and sin/cos are left as is)
SCALED = CAMS_IN + [c for c in WX_IN if not c.endswith(("_sin", "_cos"))] + \
    ["solar_elevation", "earth_sun_distance_au", "daylight_hours"] + STATIC_IN


def build_hourly_matrix(frame: pd.DataFrame, lat: float, lon: float, elevation_m: float | None) -> pd.DataFrame:
    """One location's continuous hourly frame -> all raw (unscaled) model inputs per hour.

    ``frame`` has ``time_utc`` plus ``cams_*`` / ``wx_*`` columns (same shape as
    ml.features.build_rows expects).
    """
    f = frame.set_index("time_utc").sort_index()
    if not f.index.is_unique:
        raise ValueError("duplicate timestamps in frame")
    full = pd.date_range(f.index.min(), f.index.max(), freq="h", tz="UTC")
    f = f.reindex(full)
    out = pd.DataFrame(index=full)
    for c in CAMS_IN:
        out[c] = f[c].astype(float) if c in f else np.nan
    for c in ("cams_ozone", "cams_uv_index"):
        out[f"{c}_missing"] = out[c].isna().astype(float)
    for c in WX_IN:
        if c in ("wx_wind_dir_sin", "wx_wind_dir_cos"):
            continue
        out[c] = f[c].astype(float) if c in f else np.nan
    wd = np.radians(f["wx_wind_direction_10m"].astype(float).to_numpy()) if "wx_wind_direction_10m" in f else np.nan
    out["wx_wind_dir_sin"], out["wx_wind_dir_cos"] = np.sin(wd), np.cos(wd)
    sp = solar_position(pd.Series(full), lat, lon)
    out["solar_elevation"] = sp["solar_elevation"]
    out["cos_zenith"] = sp["cos_zenith"]
    out["earth_sun_distance_au"] = sp["earth_sun_distance_au"]
    out["daylight_hours"] = sp["daylight_hours"]
    st = np.asarray(sp["true_solar_time_min"]) / 1440.0 * 2 * np.pi
    out["sin_solar_time"], out["cos_solar_time"] = np.sin(st), np.cos(st)
    doy = full.dayofyear.to_numpy()
    out["sin_doy"], out["cos_doy"] = np.sin(2 * np.pi * doy / 365.25), np.cos(2 * np.pi * doy / 365.25)
    out["lat"], out["lon"] = lat, lon
    out["elevation_m"] = elevation_m if elevation_m is not None else np.nan
    return out


def fit_scaler(hourly: pd.DataFrame) -> dict:
    """Mean/std for the standardised columns and the two targets (TRAINING data only)."""
    s = {}
    for c in SCALED:
        v = hourly[c].to_numpy(dtype=float)
        mu, sd = float(np.nanmean(v)), float(np.nanstd(v))
        s[c] = [mu, sd if sd > 1e-6 else 1.0]
    return s


def scale(hourly: pd.DataFrame, scaler: dict) -> pd.DataFrame:
    h = hourly.copy()
    for c, (mu, sd) in scaler.items():
        if c in h:
            h[c] = (h[c] - mu) / sd
    return h


def to_arrays(scaled: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Scaled hourly frame -> (encoder matrix, decoder matrix without lead_frac), NaN -> 0.

    Values are clipped to ±10 standard deviations (heavy-tailed precipitation would
    otherwise dominate a few gradients)."""
    enc = np.clip(np.nan_to_num(scaled[ENC_FEATURES].to_numpy(dtype=np.float32), nan=0.0), -10, 10)
    dec = np.clip(np.nan_to_num(scaled[[c for c in DEC_FEATURES if c != "lead_frac"]].to_numpy(dtype=np.float32),
                                nan=0.0), -10, 10)
    return enc, dec


LEAD_FRAC = (np.arange(1, DEC_LEN + 1, dtype=np.float32) / DEC_LEN)[:, None]


def encoder_decoder_windows(enc: np.ndarray, dec: np.ndarray, issue_pos: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Gather (N, ENC_LEN, F_enc) and (N, DEC_LEN, F_dec) windows for issue rows ``issue_pos``.

    Encoder rows: issue_pos-ENC_LEN+1 .. issue_pos (inclusive). Decoder rows:
    issue_pos+1 .. issue_pos+DEC_LEN. Callers must ensure the indices are in range.
    """
    e_idx = issue_pos[:, None] + np.arange(-ENC_LEN + 1, 1)[None, :]
    d_idx = issue_pos[:, None] + np.arange(1, DEC_LEN + 1)[None, :]
    E = enc[e_idx]
    D = dec[d_idx]
    D = np.concatenate([D, np.broadcast_to(LEAD_FRAC, (len(issue_pos), DEC_LEN, 1))], axis=2)
    return E, D


# --------------------------------------------------------------------------- serving
def _sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


def _lstm_layer(x: np.ndarray, W_ih, W_hh, b, h0, c0):
    """PyTorch-compatible LSTM layer (gate order i, f, g, o). x: (N, T, F)."""
    H = h0.shape[1]
    h, c = h0, c0
    outs = np.empty((x.shape[0], x.shape[1], H), dtype=np.float32)
    xw = x @ W_ih.T + b                       # (N, T, 4H)
    for t in range(x.shape[1]):
        g = xw[:, t] + h @ W_hh.T
        i, f, gg, o = _sigmoid(g[:, :H]), _sigmoid(g[:, H:2 * H]), np.tanh(g[:, 2 * H:3 * H]), _sigmoid(g[:, 3 * H:])
        c = f * c + i * gg
        h = o * np.tanh(c)
        outs[:, t] = h
    return outs, h, c


class NumpyLSTMForecaster:
    """Loads models/lstm/lstm_weights.npz + lstm_config.json and predicts with NumPy only."""

    def __init__(self, model_dir: Path = config.MODELS_LSTM):
        self.cfg = json.loads((Path(model_dir) / "lstm_config.json").read_text())
        w = np.load(Path(model_dir) / "lstm_weights.npz")
        self.w = {k: w[k].astype(np.float32) for k in w.files}
        self.layers = int(self.cfg["num_layers"])
        self.scaler = self.cfg["scaler"]
        self.target_scaler = self.cfg["target_scaler"]

    def _stack(self, prefix: str, x, h0=None, c0=None):
        N = x.shape[0]
        H = int(self.cfg["hidden_size"])
        hs, cs = [], []
        for layer in range(self.layers):
            hi = np.zeros((N, H), np.float32) if h0 is None else h0[layer]
            ci = np.zeros((N, H), np.float32) if c0 is None else c0[layer]
            b = self.w[f"{prefix}.bias_ih_l{layer}"] + self.w[f"{prefix}.bias_hh_l{layer}"]
            x, h, c = _lstm_layer(x, self.w[f"{prefix}.weight_ih_l{layer}"], self.w[f"{prefix}.weight_hh_l{layer}"], b, hi, ci)
            hs.append(h)
            cs.append(c)
        return x, hs, cs

    def predict_scaled(self, E: np.ndarray, D: np.ndarray) -> np.ndarray:
        _, h, c = self._stack("encoder", E.astype(np.float32))
        out, _, _ = self._stack("decoder", D.astype(np.float32), h, c)
        return out @ self.w["head.weight"].T + self.w["head.bias"]          # (N, DEC_LEN, 2)

    def predict(self, E: np.ndarray, D: np.ndarray) -> np.ndarray:
        """Return (N, DEC_LEN, 2) in physical units: [..., 0] ozone µg/m³, [..., 1] UV index."""
        y = self.predict_scaled(E, D)
        for k, col in enumerate(TARGET_COLS):
            mu, sd = self.target_scaler[col]
            y[..., k] = y[..., k] * sd + mu
        return y


def forecast_frame(model: NumpyLSTMForecaster, frame: pd.DataFrame, issue: pd.Timestamp, lat: float, lon: float,
                   elevation_m: float | None) -> pd.DataFrame:
    """Live-inference helper: frame (CAMS already blanked after ``issue``) -> 24 rows of predictions."""
    hourly = build_hourly_matrix(frame, lat, lon, elevation_m)
    if issue not in hourly.index:
        raise ValueError("issue hour not in frame")
    pos = hourly.index.get_loc(issue)
    if pos - ENC_LEN + 1 < 0 or pos + DEC_LEN > len(hourly) - 1:
        raise ValueError(f"need {ENC_LEN} h of history and {DEC_LEN} h of forecast around the issue hour")
    enc, dec = to_arrays(scale(hourly, model.scaler))
    E, D = encoder_decoder_windows(enc, dec, np.array([pos]))
    y = model.predict(E, D)[0]
    T = hourly.index[pos + 1: pos + DEC_LEN + 1]
    return pd.DataFrame({"target_time": T, "lead_h": np.arange(1, DEC_LEN + 1),
                         "pred_ozone": y[:, 0], "pred_uv": y[:, 1],
                         "solar_elevation": hourly["solar_elevation"].to_numpy()[pos + 1: pos + DEC_LEN + 1]})
