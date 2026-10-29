"""Train, calibrate and evaluate the LSTM forecaster (alternative to XGBoost).

python -m ml.train_lstm                     # full run (CPU; see --help for knobs)
python -m ml.train_lstm --epochs 2 --quick  # smoke test

Uses exactly the same data, the same chronological split (train <= Sep 2024,
validation Oct 2024 - Sep 2025, test >= Oct 2025), the same 30 training and 8
spatial-holdout locations, the same issue hours (00/06/12/18 UTC) and the same
metrics / split-conformal code as ml/train_xgboost.py, so the two models can be
compared row for row with ``python -m ml.compare_models``.

Model: encoder-decoder LSTM (see ml/lstm.py). One network predicts ozone and
UV for all 24 lead hours at once. Loss: L1 on standardised targets (the
models are judged on MAE). Early stopping on validation MAE.

Outputs (models/lstm/):
  lstm_weights.npz       weights for the NumPy serving path (no PyTorch needed)
  lstm_config.json       architecture, feature lists, scalers
  lstm_model.pt          PyTorch state_dict (for further training only; not served)
  conformal.json, model_metadata.json, metrics.json, feature_schema.json
"""
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import torch
from torch import nn

from ml import config
from ml import lstm as L
from ml.train_xgboost import (apply_conformal, baselines, build_climatology, by_lead, coverage, fit_conformal,
                              metrics, risk_metrics)

RS = config.RANDOM_STATE
OUT = config.MODELS_LSTM


class Seq2SeqLSTM(nn.Module):
    def __init__(self, n_enc: int, n_dec: int, hidden: int, layers: int, dropout: float):
        super().__init__()
        d = dropout if layers > 1 else 0.0
        self.encoder = nn.LSTM(n_enc, hidden, layers, batch_first=True, dropout=d)
        self.decoder = nn.LSTM(n_dec, hidden, layers, batch_first=True, dropout=d)
        self.head = nn.Linear(hidden, len(L.TARGET_COLS))

    def forward(self, E, D):
        _, state = self.encoder(E)
        out, _ = self.decoder(D, state)
        return self.head(out)


# ----------------------------------------------------------------------------- data
def prepare(clean: pd.DataFrame, scaler: dict | None = None):
    """Per location: scaled encoder/decoder matrices, raw targets, hourly index."""
    locs = {}
    for lid, g in clean.groupby("location_id"):
        first = g.iloc[0]
        hourly = L.build_hourly_matrix(g, float(first.req_lat), float(first.req_lon), float(first.wx_elev))
        locs[lid] = {"hourly": hourly, "role": first.role, "region": first.region}
    if scaler is None:
        train_end = pd.Timestamp(config.TRAIN_END)
        tr = pd.concat([v["hourly"][v["hourly"].index <= train_end] for v in locs.values() if v["role"] == "train"])
        scaler = L.fit_scaler(tr)
    for v in locs.values():
        enc, dec = L.to_arrays(L.scale(v["hourly"], scaler))
        v["enc"], v["dec"] = enc, dec
        v["y"] = v["hourly"][L.TARGET_COLS].to_numpy(dtype=np.float32)          # raw units, may contain NaN
    return locs, scaler


def issue_positions(hourly: pd.DataFrame, lo, hi, hours) -> np.ndarray:
    """Positions of issue times t with lo < t <= hi, hour in ``hours``, full enc/dec window inside the
    frame, and every target T = t+1..t+24 also <= hi (purging, as in ml.features.assign_split)."""
    idx = hourly.index
    pos = np.arange(len(idx))
    ok = (pos >= L.ENC_LEN - 1) & (pos + L.DEC_LEN <= len(idx) - 1) & np.isin(idx.hour, hours)
    if lo is not None:
        ok &= idx > lo
    if hi is not None:
        ok &= (idx + pd.Timedelta(hours=L.DEC_LEN)) <= hi
    return pos[ok]


def gather(locs, ids, lo, hi, hours):
    E, D, Y, meta = [], [], [], []
    for lid in ids:
        v = locs[lid]
        p = issue_positions(v["hourly"], lo, hi, hours)
        if not len(p):
            continue
        e, d = L.encoder_decoder_windows(v["enc"], v["dec"], p)
        y = v["y"][p[:, None] + np.arange(1, L.DEC_LEN + 1)[None, :]]
        E.append(e)
        D.append(d)
        Y.append(y)
        meta.append(pd.DataFrame({"location_id": lid, "issue_time": v["hourly"].index[p]}))
    return np.concatenate(E), np.concatenate(D), np.concatenate(Y), pd.concat(meta, ignore_index=True)


# ----------------------------------------------------------------------------- training
def _to_scaled_target(Y, ts):
    out = np.empty_like(Y)
    for k, c in enumerate(L.TARGET_COLS):
        mu, sd = ts[c]
        out[..., k] = (Y[..., k] - mu) / sd
    return out


def predict_torch(model, E, D, ts, batch=4096):
    model.eval()
    outs = []
    with torch.no_grad():
        for i in range(0, len(E), batch):
            outs.append(model(torch.from_numpy(E[i:i + batch]), torch.from_numpy(D[i:i + batch])).numpy())
    y = np.concatenate(outs)
    for k, c in enumerate(L.TARGET_COLS):
        mu, sd = ts[c]
        y[..., k] = y[..., k] * sd + mu
    return y


def postprocess_seq(P, solar_elev):
    P = np.maximum(P, 0.0)
    P[..., 1] = np.where(solar_elev < -1.0, 0.0, P[..., 1])
    return P


def solar_for(locs, meta):
    """Solar elevation at every target hour, (N, 24)."""
    out = np.empty((len(meta), L.DEC_LEN), np.float32)
    for lid, g in meta.groupby("location_id"):
        h = locs[lid]["hourly"]
        pos = h.index.get_indexer(g["issue_time"])
        out[g.index] = h["solar_elevation"].to_numpy()[pos[:, None] + np.arange(1, L.DEC_LEN + 1)[None, :]]
    return out


def train(args) -> dict:
    t_all = time.perf_counter()
    torch.manual_seed(RS)
    np.random.seed(RS)
    torch.set_num_threads(args.threads or os.cpu_count())
    clean = pd.read_parquet(config.INTERMEDIATE / "cleaned.parquet")
    clim = build_climatology(clean)
    locs, scaler = prepare(clean)
    ts = {c: scaler[c] for c in L.TARGET_COLS}
    train_ids = [l[0] for l in config.LOCATIONS if l[5] == "train"]
    hold_ids = [l[0] for l in config.LOCATIONS if l[5] == "spatial_holdout"]
    tr_end, va_end = pd.Timestamp(config.TRAIN_END), pd.Timestamp(config.VAL_END)

    # Training windows are cut on the fly from per-location matrices (memory stays ~1 GB).
    train_hours = tuple(range(0, 24, args.train_stride))
    index = [(k, p) for k, lid in enumerate(train_ids)
             for p in issue_positions(locs[lid]["hourly"], None, tr_end, train_hours)]
    index = np.array(index, dtype=np.int64)
    if args.quick:
        index = index[np.random.default_rng(RS).choice(len(index), min(len(index), 30000), replace=False)]
    enc_by = [locs[lid]["enc"] for lid in train_ids]
    dec_by = [locs[lid]["dec"] for lid in train_ids]
    ys_by = []
    for lid in train_ids:
        y = _to_scaled_target(locs[lid]["y"], ts)
        ys_by.append(y)
    Eva, Dva, Yva, Mva = gather(locs, train_ids, tr_end, va_end, config.ISSUE_HOURS_UTC)
    print(f"train sequences {len(index):,}  validation sequences {len(Eva):,}  "
          f"enc ({L.ENC_LEN}, {len(L.ENC_FEATURES)}) dec ({L.DEC_LEN}, {len(L.DEC_FEATURES)})", flush=True)
    dec_off = np.arange(1, L.DEC_LEN + 1)

    def batch_of(rows):
        E, D, Y = [], [], []
        for k in np.unique(rows[:, 0]):
            p = rows[rows[:, 0] == k, 1]
            e, d = L.encoder_decoder_windows(enc_by[k], dec_by[k], p)
            E.append(e)
            D.append(d)
            Y.append(ys_by[k][p[:, None] + dec_off[None, :]])
        Y = np.concatenate(Y)
        M = np.isfinite(Y)
        return (torch.from_numpy(np.concatenate(E)), torch.from_numpy(np.ascontiguousarray(np.concatenate(D))),
                torch.from_numpy(np.nan_to_num(Y)), torch.from_numpy(M))

    model = Seq2SeqLSTM(len(L.ENC_FEATURES), len(L.DEC_FEATURES), args.hidden, args.layers, args.dropout)
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-5)
    sched = torch.optim.lr_scheduler.ReduceLROnPlateau(opt, factor=0.5, patience=1)
    sol_va = solar_for(locs, Mva)
    rng = np.random.default_rng(RS)
    best, best_state, bad, history = np.inf, None, 0, []
    for epoch in range(1, args.epochs + 1):
        model.train()
        t0 = time.perf_counter()
        perm = index[rng.permutation(len(index))]
        tot = 0.0
        for i in range(0, len(perm), args.batch):
            Eb, Db, Yb, Mb = batch_of(perm[i:i + args.batch])
            pred = model(Eb, Db)
            loss = (pred - Yb).abs()[Mb].mean()   # ozone and UV weighted equally in standardised units
            opt.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            tot += loss.item() * len(Eb)
        P = postprocess_seq(predict_torch(model, Eva, Dva, ts), sol_va)
        mae = {c: float(np.nanmean(np.abs(P[..., k] - Yva[..., k]))) for k, c in enumerate(["ozone", "uv"])}
        score = mae["ozone"] / ts["cams_ozone"][1] + mae["uv"] / ts["cams_uv_index"][1]
        sched.step(score)
        history.append({"epoch": epoch, "train_l1_scaled": tot / len(perm), "val_mae_ozone": mae["ozone"],
                        "val_mae_uv": mae["uv"], "seconds": round(time.perf_counter() - t0, 1),
                        "lr": opt.param_groups[0]["lr"]})
        print(f"epoch {epoch:2d}  train L1 {tot / len(perm):.4f}  val MAE ozone {mae['ozone']:.3f}  "
              f"uv {mae['uv']:.4f}  ({history[-1]['seconds']}s)", flush=True)
        if score < best - 1e-4:
            best, best_state, bad = score, {k: v.clone() for k, v in model.state_dict().items()}, 0
        else:
            bad += 1
            if bad >= args.patience:
                print("early stop", flush=True)
                break
    model.load_state_dict(best_state)
    train_seconds = round(time.perf_counter() - t_all, 1)
    del ys_by, index

    # ----------------------------------------------------------------- save + NumPy export
    OUT.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), OUT / "lstm_model.pt")
    np.savez_compressed(OUT / "lstm_weights.npz", **{k: v.numpy() for k, v in model.state_dict().items()})
    cfg = {"architecture": "encoder-decoder LSTM (seq2seq), direct 24 h output", "enc_len": L.ENC_LEN,
           "dec_len": L.DEC_LEN, "hidden_size": args.hidden, "num_layers": args.layers, "dropout": args.dropout,
           "enc_features": L.ENC_FEATURES, "dec_features": L.DEC_FEATURES, "targets": L.TARGET_COLS,
           "scaler": scaler, "target_scaler": ts}
    (OUT / "lstm_config.json").write_text(json.dumps(cfg, indent=2))
    npm = L.NumpyLSTMForecaster(OUT)
    parity = float(np.abs(npm.predict(Eva[:256], Dva[:256]) - predict_torch(model, Eva[:256], Dva[:256], ts)).max())
    print(f"NumPy vs PyTorch max abs difference: {parity:.2e}", flush=True)
    assert parity < 1e-2, "NumPy serving path does not match PyTorch"

    # ----------------------------------------------------------------- validation: by lead + conformal
    def rows_frame(Pseq, meta, proc_name):
        """Expand (N,24,2) predictions onto ml.features rows of the same split for identical scoring."""
        d = pd.read_parquet(config.PROCESSED / proc_name).dropna(subset=["y_ozone", "y_uv"]).reset_index(drop=True)
        key = meta.assign(k=np.arange(len(meta)))
        d = d.merge(key, on=["location_id", "issue_time"], how="left")
        missing = int(d["k"].isna().sum())
        d = d[d["k"].notna()].reset_index(drop=True)
        k, h = d["k"].to_numpy(int), d["lead_h"].to_numpy(int) - 1
        d["p_ozone"], d["p_uv"] = Pseq[k, h, 0], Pseq[k, h, 1]
        return d, missing

    P_va = postprocess_seq(predict_torch(model, Eva, Dva, ts), sol_va)
    va, va_missing = rows_frame(P_va, Mva, "val.parquet")
    results: dict = {"generated_at": datetime.now(timezone.utc).isoformat(), "model": "LSTM",
                     "train_history": history, "train_seconds": train_seconds,
                     "numpy_vs_pytorch_max_abs_diff": parity, "ozone": {}, "uv": {}}
    conformal = {}
    for t in ["ozone", "uv"]:
        y, p = va[f"y_{t}"].to_numpy(), va[f"p_{t}"].to_numpy()
        results[t]["final_model_validation_full_train"] = metrics(y, p)
        results[t]["models_validation"] = {"LSTM": metrics(y, p)}
        results[t]["selected_family"] = "LSTM"
        results[t]["baselines_validation"] = baselines(va, t, clim)
        results[t]["validation_by_lead"] = by_lead(va, p, t)
        conformal[t] = fit_conformal(t, va["lead_h"].to_numpy(), p, y)
        lo, hi = apply_conformal(conformal[t], t, va["lead_h"].to_numpy(), p)
        results[t]["conformal_validation_coverage"] = coverage(y, lo, hi)
    results["rows_with_targets"] = {"val": int(len(va)), "val_rows_without_lstm_window": va_missing}

    # ----------------------------------------------------------------- TEST (once) + spatial holdout
    print("\n=== TEST (untouched) ===", flush=True)
    results["test"], results["spatial_holdout_test"] = {}, {}
    for name, ids, proc in [("test", train_ids, "test.parquet"), ("spatial_holdout", hold_ids, "spatial_holdout.parquet")]:
        E, D, _, M = gather(locs, ids, va_end, None, config.ISSUE_HOURS_UTC)
        P = postprocess_seq(predict_torch(model, E, D, ts), solar_for(locs, M))
        fr, miss = rows_frame(P, M, proc)
        if name == "spatial_holdout":
            fr = fr[fr["split"] == "holdout_test"].reset_index(drop=True)
        store = results["test"] if name == "test" else results["spatial_holdout_test"]
        results["rows_with_targets"][name] = int(len(fr))
        results["rows_with_targets"][f"{name}_rows_without_lstm_window"] = miss
        for t in ["ozone", "uv"]:
            y, p = fr[f"y_{t}"].to_numpy(), fr[f"p_{t}"].to_numpy()
            lo, hi = apply_conformal(conformal[t], t, fr["lead_h"].to_numpy(), p)
            native = fr["target_native"].to_numpy()
            entry = {"model": metrics(y, p), "model_native_hours_only": metrics(y[native], p[native]),
                     "baselines": baselines(fr, t, clim) if name == "test" else {
                         "Persistence (latest value at issue time)": metrics(y, fr[f"{t}_t"].to_numpy()),
                         "Same hour, previous day": metrics(y, fr[f"{t}_same_hour_prev_day"].to_numpy())},
                     "interval_90": coverage(y, lo, hi)}
            if t == "uv":
                day = fr["solar_elevation"].to_numpy() > 0
                entry["model_daytime_only"] = metrics(y[day], p[day])
                entry["risk_classification"] = risk_metrics(y, p, day)
            if name == "test":
                entry["by_lead"] = by_lead(fr, p, t)
                entry["by_region"] = {r: metrics(y[(fr["region"] == r).to_numpy()], p[(fr["region"] == r).to_numpy()])
                                      for r in sorted(fr["region"].unique())}
            else:
                entry["by_location"] = {l: metrics(y[(fr["location_id"] == l).to_numpy()], p[(fr["location_id"] == l).to_numpy()])
                                        for l in sorted(fr["location_id"].unique())}
            store[t] = entry
            print(name, t, entry["model"], entry["interval_90"], flush=True)
    results["total_runtime_seconds"] = round(time.perf_counter() - t_all, 1)

    # ----------------------------------------------------------------- artifacts
    (OUT / "conformal.json").write_text(json.dumps(conformal, indent=2))
    schema = {t: {"features": {"encoder": L.ENC_FEATURES, "decoder": L.DEC_FEATURES}, "target": config.TARGETS[t],
                  "unit": "µg/m³ (surface ozone mass concentration)" if t == "ozone" else "UV index (dimensionless, WHO scale)"}
              for t in ["ozone", "uv"]}
    schema["uv"]["uses_predicted_ozone"] = False
    schema["horizons"] = config.HORIZONS
    (OUT / "feature_schema.json").write_text(json.dumps(schema, indent=2))
    n_params = int(sum(p.numel() for p in model.parameters()))
    hp = {"hidden_size": args.hidden, "num_layers": args.layers, "dropout": args.dropout, "lr": args.lr,
          "batch_size": args.batch, "max_epochs": args.epochs, "epochs_run": len(history),
          "early_stopping_patience": args.patience, "train_issue_stride_h": args.train_stride,
          "encoder_hours": L.ENC_LEN, "decoder_hours": L.DEC_LEN, "loss": "L1 on standardised targets",
          "parameters": n_params}
    meta = {
        "model_version": config.MODEL_VERSION + "-lstm",
        "dataset_version": config.DATASET_VERSION,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "forecast_formulation": "encoder-decoder LSTM: 48 h history -> 24 hourly outputs in one pass",
        "training_period_issue_time_utc": [None, config.TRAIN_END],
        "validation_period_issue_time_utc": [config.TRAIN_END, config.VAL_END],
        "test_period_issue_time_utc": [config.VAL_END, None],
        "training_locations": train_ids,
        "spatial_holdout_locations": hold_ids,
        "models": {t: {"algorithm": "LSTM", "hyperparameters": hp, "target": config.TARGETS[t],
                       "n_features": len(L.ENC_FEATURES) + len(L.DEC_FEATURES)} for t in ["ozone", "uv"]},
        "uncertainty": "split-conformal (Mondrian by lead bucket × predicted-value bin), 90 % nominal, calibrated on validation period",
        "validation_metrics": {t: results[t]["final_model_validation_full_train"] for t in ["ozone", "uv"]},
        "test_metrics": {t: results["test"][t]["model"] for t in ["ozone", "uv"]},
        "serving": "NumPy forward pass from lstm_weights.npz (PyTorch not required at inference)",
        "data_sources": [
            "CAMS global atmospheric composition forecasts (ECMWF/Copernicus) via Open-Meteo Air Quality API (CC BY 4.0)",
            "Archived NWP forecasts via Open-Meteo Historical Forecast API, best_match (CC BY 4.0)",
            "Solar geometry: NOAA solar position equations (computed)",
        ],
    }
    (OUT / "model_metadata.json").write_text(json.dumps(meta, indent=2, default=str))
    (OUT / "metrics.json").write_text(json.dumps(results, indent=2, default=str))
    print(f"\nsaved to {OUT}  ({results['total_runtime_seconds']} s)")
    return results


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--epochs", type=int, default=25)
    ap.add_argument("--hidden", type=int, default=96)
    ap.add_argument("--layers", type=int, default=2)
    ap.add_argument("--dropout", type=float, default=0.1)
    ap.add_argument("--lr", type=float, default=2e-3)
    ap.add_argument("--batch", type=int, default=256)
    ap.add_argument("--patience", type=int, default=4)
    ap.add_argument("--train-stride", type=int, default=2, help="use every Nth hour as a training issue time")
    ap.add_argument("--threads", type=int, default=0)
    ap.add_argument("--quick", action="store_true", help="30k training sequences (smoke test)")
    train(ap.parse_args())


if __name__ == "__main__":
    main()
