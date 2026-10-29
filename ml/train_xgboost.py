"""Benchmark, select, calibrate and save the OzoneGuard forecasting models.

python -m ml.train_xgboost    # full benchmark + artifacts (~CPU minutes)

Artifacts go to models/xgboost/ (the shared climatology to models/climatology.parquet).
The LSTM alternative is trained separately by ml/train_lstm.py; compare both with
`python -m ml.compare_models`.

Steps
1. Baselines: persistence, same-hour-previous-day, train climatology, raw NWP UV.
2. Model families on the VALIDATION period: Ridge, RandomForest, HistGB,
   XGBoost, LightGBM (+ per-horizon LightGBM variant).
3. UV ablation: without ozone / with observed ozone lags / with predicted ozone.
4. Select per target (lowest validation MAE; simpler model if within 1 %).
5. Split-conformal (Mondrian) 90 % intervals calibrated on validation.
6. ONE evaluation on the untouched test period + spatial-holdout locations.
7. Explainability: gain, permutation importance, SHAP (TreeSHAP via LightGBM).
8. Save models/xgboost/*.json + *.joblib, metadata, feature schema, metrics, climatology.
"""
from __future__ import annotations

import json
import os
import pickle
import time
from datetime import datetime, timezone

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.linear_model import Ridge
from sklearn.metrics import (accuracy_score, confusion_matrix, f1_score, mean_absolute_error,
                             mean_squared_error, precision_recall_fscore_support, r2_score)
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from ml import config
from ml import features as F
from ml.risk import RISK_LABELS, uv_risk_index

RS = config.RANDOM_STATE
ALPHA = 0.10  # 90 % nominal intervals
LEAD_BINS = [(1, 3), (4, 6), (7, 12), (13, 24)]
UV_BINS = [0.0, 0.5, 3.0, 6.0, 9.0, 99.0]
OZ_BINS = [0.0, 40.0, 80.0, 120.0, 999.0]


def metrics(y, p) -> dict:
    m = np.isfinite(y) & np.isfinite(p)
    y, p = y[m], p[m]
    return {"n": int(m.sum()), "mae": float(mean_absolute_error(y, p)),
            "rmse": float(np.sqrt(mean_squared_error(y, p))), "r2": float(r2_score(y, p))}


def load():
    d = {s: pd.read_parquet(config.PROCESSED / f"{s}.parquet") for s in ["train", "val", "test"]}
    d["holdout"] = pd.read_parquet(config.PROCESSED / "spatial_holdout.parquet")
    return d


def postprocess(target: str, pred: np.ndarray, X: pd.DataFrame) -> np.ndarray:
    pred = np.maximum(pred, 0.0)
    if target == "uv":  # physical constraint: no UV with the sun below the horizon
        pred = np.where(X["solar_elevation"].to_numpy() < -1.0, 0.0, pred)
    return pred


# ----------------------------------------------------------------------------------
def make_models(n_rows: int) -> dict:
    return {
        "Ridge": lambda: make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), Ridge(alpha=1.0)),
        "RandomForest": lambda: make_pipeline(SimpleImputer(strategy="median"),
                                              RandomForestRegressor(n_estimators=100, max_depth=20, min_samples_leaf=5,
                                                                    max_features=0.5, n_jobs=-1, random_state=RS)),
        "HistGradientBoosting": lambda: HistGradientBoostingRegressor(max_iter=600, learning_rate=0.06, max_leaf_nodes=63,
                                                                      min_samples_leaf=40, l2_regularization=1.0,
                                                                      early_stopping=False, random_state=RS),
        "XGBoost": lambda: xgb.XGBRegressor(n_estimators=700, learning_rate=0.05, max_depth=8, subsample=0.8,
                                            colsample_bytree=0.8, min_child_weight=20, tree_method="hist",
                                            n_jobs=os.cpu_count(), random_state=RS),
        "LightGBM": lambda: lgb.LGBMRegressor(n_estimators=900, learning_rate=0.05, num_leaves=127, min_child_samples=50,
                                              subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0,
                                              n_jobs=os.cpu_count(), random_state=RS, verbose=-1),
    }


RF_MAX_ROWS = 300_000
BENCH_ROWS = 600_000  # RandomForest is trained on a random subsample (CPU/memory budget)


def fit_eval(name, factory, Xtr, ytr, Xva, yva, target):
    t0 = time.perf_counter()
    model = factory()
    if name == "RandomForest" and len(Xtr) > RF_MAX_ROWS:
        idx = np.random.default_rng(RS).choice(len(Xtr), RF_MAX_ROWS, replace=False)
        model.fit(Xtr.iloc[idx], ytr[idx])
    else:
        model.fit(Xtr, ytr)
    train_s = time.perf_counter() - t0
    t0 = time.perf_counter()
    p = postprocess(target, model.predict(Xva), Xva)
    infer_ms_per_1k = (time.perf_counter() - t0) / len(Xva) * 1e6
    size_mb = len(pickle.dumps(model)) / 1e6
    m = metrics(yva, p)
    m.update({"train_seconds": round(train_s, 1), "inference_ms_per_1k_rows": round(infer_ms_per_1k, 2),
              "model_size_mb": round(size_mb, 2)})
    return model, p, m


def baselines(df: pd.DataFrame, target: str, clim: pd.DataFrame) -> dict:
    y = df[f"y_{target}"].to_numpy()
    out = {"Persistence (latest value at issue time)": metrics(y, df[f"{target}_t"].to_numpy()),
           "Same hour, previous day": metrics(y, df[f"{target}_same_hour_prev_day"].to_numpy())}
    c = climatology_lookup(df, clim, target)
    out["Climatology (train-period month × hour mean)"] = metrics(y, c)
    if target == "uv":
        out["Raw NWP UV forecast (Open-Meteo best_match)"] = metrics(y, df["fc_uv_index"].to_numpy())
    return out


# ---- climatology / anomaly ---------------------------------------------------------
def build_climatology(clean: pd.DataFrame) -> pd.DataFrame:
    """Per location × calendar month × UTC hour mean and std, TRAIN PERIOD ONLY."""
    tr = clean[clean["time_utc"] <= pd.Timestamp(config.TRAIN_END)].copy()
    tr["month"], tr["hour"] = tr["time_utc"].dt.month, tr["time_utc"].dt.hour
    g = tr.groupby(["location_id", "month", "hour"])
    clim = g.agg(ozone_mean=("cams_ozone", "mean"), ozone_std=("cams_ozone", "std"), ozone_n=("cams_ozone", "count"),
                 uv_mean=("cams_uv_index", "mean"), uv_std=("cams_uv_index", "std")).reset_index()
    loc = clean.groupby("location_id")[["req_lat", "req_lon", "role"]].first().reset_index()
    return clim.merge(loc, on="location_id")


def climatology_lookup(df: pd.DataFrame, clim: pd.DataFrame, target: str) -> np.ndarray:
    k = df[["location_id"]].copy()
    k["month"], k["hour"] = df["target_time"].dt.month.to_numpy(), df["target_time"].dt.hour.to_numpy()
    m = k.merge(clim[["location_id", "month", "hour", f"{target}_mean"]], on=["location_id", "month", "hour"], how="left")
    return m[f"{target}_mean"].to_numpy()


# ---- conformal -------------------------------------------------------------------------
def _bin_keys(target: str, lead: np.ndarray, pred: np.ndarray) -> list[str]:
    lb = np.select([(lead >= a) & (lead <= b) for a, b in LEAD_BINS], [f"{a}-{b}" for a, b in LEAD_BINS], "13-24")
    edges = UV_BINS if target == "uv" else OZ_BINS
    vb = np.clip(np.digitize(pred, edges) - 1, 0, len(edges) - 2)
    return [f"lead{l}|v{v}" for l, v in zip(lb, vb)]


def fit_conformal(target, lead, pred, y, alpha=ALPHA) -> dict:
    keys = np.array(_bin_keys(target, lead, pred))
    res = np.abs(y - pred)
    table = {}
    for k in np.unique(keys):
        r = np.sort(res[keys == k])
        n = len(r)
        q = r[min(n - 1, int(np.ceil((n + 1) * (1 - alpha))) - 1)] if n >= 30 else np.quantile(res, 1 - alpha)
        table[k] = {"q": float(q), "n": int(n)}
    return {"alpha": alpha, "global_q": float(np.quantile(res, 1 - alpha)), "bins": table,
            "lead_bins": LEAD_BINS, "value_edges": UV_BINS if target == "uv" else OZ_BINS}


def apply_conformal(conf: dict, target, lead, pred):
    keys = _bin_keys(target, np.asarray(lead), np.asarray(pred))
    q = np.array([conf["bins"].get(k, {"q": conf["global_q"]})["q"] for k in keys])
    return np.maximum(pred - q, 0.0), pred + q


def coverage(y, lo, hi) -> dict:
    m = np.isfinite(y)
    return {"coverage": float(((y[m] >= lo[m]) & (y[m] <= hi[m])).mean()), "mean_width": float((hi[m] - lo[m]).mean())}


# ---- explainability ------------------------------------------------------------------
def explain(model, X: pd.DataFrame, y: np.ndarray, target: str, feats: list[str]) -> dict:
    sample = X.sample(min(20000, len(X)), random_state=RS)
    ys = y[X.index.get_indexer(sample.index)]
    out = {}
    if isinstance(model, lgb.LGBMRegressor):
        gain = model.booster_.feature_importance(importance_type="gain")
        out["gain_share"] = dict(sorted(zip(feats, (gain / gain.sum()).round(4).tolist()), key=lambda kv: -kv[1]))
        contrib = model.predict(sample, pred_contrib=True)[:, :-1]
        shap_abs = np.abs(contrib).mean(axis=0)
        out["mean_abs_shap"] = dict(sorted(zip(feats, shap_abs.round(4).tolist()), key=lambda kv: -kv[1]))
    elif isinstance(model, xgb.XGBRegressor):
        booster = model.get_booster()
        gain = booster.get_score(importance_type="total_gain")
        tot = sum(gain.values()) or 1.0
        out["gain_share"] = dict(sorted(((f, round(gain.get(f, 0.0) / tot, 4)) for f in feats), key=lambda kv: -kv[1]))
        contrib = booster.predict(xgb.DMatrix(sample, feature_names=feats), pred_contribs=True)[:, :-1]  # TreeSHAP
        shap_abs = np.abs(contrib).mean(axis=0)
        out["mean_abs_shap"] = dict(sorted(zip(feats, shap_abs.round(4).tolist()), key=lambda kv: -kv[1]))
    pi = permutation_importance(model, sample, ys, scoring="neg_mean_absolute_error", n_repeats=3,
                                random_state=RS, n_jobs=1)
    out["permutation_mae_increase"] = dict(sorted(zip(feats, pi.importances_mean.round(4).tolist()), key=lambda kv: -kv[1]))
    return out


def risk_metrics(y_true, y_pred, daytime) -> dict:
    out = {}
    for label, mask in [("all_hours", np.ones_like(daytime, bool)), ("daytime_only", daytime)]:
        m = mask & np.isfinite(y_true)
        t, p = uv_risk_index(y_true[m]), uv_risk_index(y_pred[m])
        pr, rc, f1, sup = precision_recall_fscore_support(t, p, labels=range(5), zero_division=0)
        out[label] = {"accuracy": float(accuracy_score(t, p)), "macro_f1": float(f1_score(t, p, average="macro")),
                      "weighted_f1": float(f1_score(t, p, average="weighted")),
                      "per_class": {RISK_LABELS[i]: {"precision": float(pr[i]), "recall": float(rc[i]), "f1": float(f1[i]),
                                                     "support": int(sup[i])} for i in range(5)},
                      "confusion_matrix": confusion_matrix(t, p, labels=range(5)).tolist(), "labels": RISK_LABELS}
    return out


def by_lead(df, pred, target) -> dict:
    y = df[f"y_{target}"].to_numpy()
    out = {}
    for h in config.HORIZONS:
        m = df["lead_h"].to_numpy() == h
        out[h] = {"model": metrics(y[m], pred[m]),
                  "persistence": metrics(y[m], df[f"{target}_t"].to_numpy()[m]),
                  "same_hour_prev_day": metrics(y[m], df[f"{target}_same_hour_prev_day"].to_numpy()[m])}
    return out


# ----------------------------------------------------------------------------------
def run() -> dict:
    t_all = time.perf_counter()
    d = load()
    clean = pd.read_parquet(config.INTERMEDIATE / "cleaned.parquet")
    clim = build_climatology(clean)
    results: dict = {"generated_at": datetime.now(timezone.utc).isoformat(), "rows": {k: int(len(v)) for k, v in d.items()}}
    for k in ["train", "val", "test", "holdout"]:
        d[k] = d[k].dropna(subset=["y_ozone", "y_uv"]).reset_index(drop=True)
    results["rows_with_targets"] = {k: int(len(v)) for k, v in d.items()}
    tr, va, te, ho = d["train"], d["val"], d["test"], d["holdout"]
    ho_test = ho[ho["split"] == "holdout_test"].reset_index(drop=True)

    final_models, selected = {}, {}
    # Benchmarks run on a random subsample of the TRAIN period (CPU budget: 2 cores);
    # the selected family is then refit on the full training period.
    trs = tr.sample(min(BENCH_ROWS, len(tr)), random_state=RS).reset_index(drop=True)
    results["benchmark_train_rows"] = int(len(trs))
    order = list(make_models(1).keys())
    for target, feats in [("ozone", F.OZONE_FEATURES), ("uv", F.UV_FEATURES_NO_OZONE)]:
        print(f"\n=== {target} ===")
        ytr, yva = trs[f"y_{target}"].to_numpy(), va[f"y_{target}"].to_numpy()
        bench = {"baselines_validation": baselines(va, target, clim), "models_validation": {}}
        for name, factory in make_models(len(trs)).items():
            model, p, m = fit_eval(name, factory, trs[feats], ytr, va[feats], yva, target)
            bench["models_validation"][name] = m
            del model, p
            print(f"{name:22s} MAE={m['mae']:.3f} RMSE={m['rmse']:.3f} R2={m['r2']:.3f} t={m['train_seconds']}s")
        best = min(bench["models_validation"], key=lambda n: bench["models_validation"][n]["mae"])
        best_mae = bench["models_validation"][best]["mae"]
        for n in order:  # prefer the simpler family if within 1 % of the best MAE
            if bench["models_validation"][n]["mae"] <= best_mae * 1.01:
                best = n
                break
        bench["selected_family"] = best
        selected[target] = best

        if best in ("LightGBM", "XGBoost", "HistGradientBoosting"):
            ph_pred = np.full(len(va), np.nan)
            factory = make_models(1)[best]
            t0 = time.perf_counter()
            for h in config.HORIZONS:
                mt, mv = (trs["lead_h"] == h).to_numpy(), (va["lead_h"] == h).to_numpy()
                mh = factory()
                mh.fit(trs.loc[mt, feats], ytr[mt])
                ph_pred[mv] = postprocess(target, mh.predict(va.loc[mv, feats]), va.loc[mv, feats])
            ph = metrics(yva, ph_pred)
            ph["train_seconds"] = round(time.perf_counter() - t0, 1)
            bench["per_horizon_variant_validation"] = ph
            bench["single_multi_horizon_validation"] = bench["models_validation"][best]
            print(f"per-horizon {best}: MAE={ph['mae']:.3f}")
        results[target] = bench

    # ------------------------------------------------------------- UV ablation (ozone) on the subsample
    print("\n=== UV ablation ===")
    fam = selected["uv"]
    factory = make_models(1)[fam]
    oz_sub = make_models(1)[selected["ozone"]]()
    oz_sub.fit(trs[F.OZONE_FEATURES], trs["y_ozone"])
    trs = trs.assign(pred_ozone=postprocess("ozone", oz_sub.predict(trs[F.OZONE_FEATURES]), trs))
    va_s = va.assign(pred_ozone=postprocess("ozone", oz_sub.predict(va[F.OZONE_FEATURES]), va))
    abl = {"no_ozone": results["uv"]["models_validation"][fam]}
    for label, feats in [("with_observed_surface_ozone_lags", F.UV_FEATURES_WITH_OZONE_LAGS),
                         ("with_predicted_surface_ozone", F.UV_FEATURES_WITH_PRED_OZONE)]:
        model, p, m = fit_eval(fam, factory, trs[feats], trs["y_uv"].to_numpy(), va_s[feats], va_s["y_uv"].to_numpy(), "uv")
        abl[label] = m
        print(f"{label}: MAE={m['mae']:.3f}")
    base_mae = abl["no_ozone"]["mae"]
    best_lab = min(abl, key=lambda k: abl[k]["mae"])
    use_label = best_lab if abl[best_lab]["mae"] <= base_mae * 0.99 else "no_ozone"
    abl["decision_rule"] = "keep an ozone input only if validation MAE improves by >= 1 %"
    abl["decision"] = use_label
    results["uv_ozone_ablation_validation"] = abl
    del trs, va_s, oz_sub

    # ------------------------------------------------------------- final refit on the FULL training period
    print("\n=== final refit (full train) ===")
    uv_feats = {"no_ozone": F.UV_FEATURES_NO_OZONE, "with_observed_surface_ozone_lags": F.UV_FEATURES_WITH_OZONE_LAGS,
                "with_predicted_surface_ozone": F.UV_FEATURES_WITH_PRED_OZONE}[use_label]
    oz_model, _, oz_m = fit_eval(selected["ozone"], make_models(1)[selected["ozone"]], tr[F.OZONE_FEATURES],
                                 tr["y_ozone"].to_numpy(), va[F.OZONE_FEATURES], va["y_ozone"].to_numpy(), "ozone")
    tr = tr.assign(pred_ozone=postprocess("ozone", oz_model.predict(tr[F.OZONE_FEATURES]), tr))
    va = va.assign(pred_ozone=postprocess("ozone", oz_model.predict(va[F.OZONE_FEATURES]), va))
    uv_model, _, uv_m = fit_eval(selected["uv"], make_models(1)[selected["uv"]], tr[uv_feats], tr["y_uv"].to_numpy(),
                                 va[uv_feats], va["y_uv"].to_numpy(), "uv")
    for target, model, feats, m in [("ozone", oz_model, F.OZONE_FEATURES, oz_m), ("uv", uv_model, uv_feats, uv_m)]:
        results[target]["final_model_validation_full_train"] = m
        pva = postprocess(target, model.predict(va[feats]), va)
        yva = va[f"y_{target}"].to_numpy()
        results[target]["validation_by_lead"] = by_lead(va, pva, target)
        conf = fit_conformal(target, va["lead_h"].to_numpy(), pva, yva)
        lo, hi = apply_conformal(conf, target, va["lead_h"].to_numpy(), pva)
        results[target]["conformal_validation_coverage"] = coverage(yva, lo, hi)
        final_models[target] = {"model": model, "features": feats, "conformal": conf, "family": selected[target]}
        print(target, m)
    final_models["uv"]["uses_predicted_ozone"] = use_label == "with_predicted_surface_ozone"
    oz = final_models["ozone"]

    # ------------------------------------------------------------- TEST (once)
    print("\n=== TEST (untouched) ===")
    results["test"], results["spatial_holdout_test"] = {}, {}
    for name, frame, store in [("test", te, results["test"]), ("spatial_holdout", ho_test, results["spatial_holdout_test"])]:
        frame = frame.assign(pred_ozone=postprocess("ozone", oz["model"].predict(frame[oz["features"]]), frame))
        for target in ["ozone", "uv"]:
            fm = final_models[target]
            p = postprocess(target, fm["model"].predict(frame[fm["features"]]), frame)
            y = frame[f"y_{target}"].to_numpy()
            lo, hi = apply_conformal(fm["conformal"], target, frame["lead_h"].to_numpy(), p)
            native = frame["target_native"].to_numpy()
            entry = {"model": metrics(y, p), "model_native_hours_only": metrics(y[native], p[native]),
                     "baselines": baselines(frame, target, clim) if name == "test" else {
                         "Persistence (latest value at issue time)": metrics(y, frame[f"{target}_t"].to_numpy()),
                         "Same hour, previous day": metrics(y, frame[f"{target}_same_hour_prev_day"].to_numpy())},
                     "interval_90": coverage(y, lo, hi)}
            if target == "uv":
                day = frame["solar_elevation"].to_numpy() > 0
                entry["model_daytime_only"] = metrics(y[day], p[day])
                entry["risk_classification"] = risk_metrics(y, p, day)
            if name == "test":
                entry["by_lead"] = by_lead(frame, p, target)
                entry["by_region"] = {r: metrics(y[(frame["region"] == r).to_numpy()], p[(frame["region"] == r).to_numpy()])
                                      for r in sorted(frame["region"].unique())}
            else:
                entry["by_location"] = {l: metrics(y[(frame["location_id"] == l).to_numpy()], p[(frame["location_id"] == l).to_numpy()])
                                        for l in sorted(frame["location_id"].unique())}
            store[target] = entry
            print(name, target, entry["model"], entry["interval_90"])

    # quantile-regression alternative for uncertainty (comparison only)
    results["quantile_regression_comparison_test"] = {}
    for target in ["ozone", "uv"]:
        fm = final_models[target]
        feats = fm["features"]
        trq = tr if "pred_ozone" not in feats else tr
        teq = te.assign(pred_ozone=postprocess("ozone", oz["model"].predict(te[oz["features"]]), te))
        qs = {}
        for a in (0.05, 0.95):
            mq = lgb.LGBMRegressor(objective="quantile", alpha=a, n_estimators=400, learning_rate=0.05, num_leaves=63,
                                   min_child_samples=50, n_jobs=os.cpu_count(), random_state=RS, verbose=-1)
            idx = np.random.default_rng(RS).choice(len(trq), min(len(trq), 600_000), replace=False)
            mq.fit(trq.iloc[idx][feats], trq.iloc[idx][f"y_{target}"])
            qs[a] = mq.predict(teq[feats])
        results["quantile_regression_comparison_test"][target] = coverage(teq[f"y_{target}"].to_numpy(),
                                                                          np.maximum(qs[0.05], 0), qs[0.95])

    # ------------------------------------------------------------- explainability
    results["explainability_validation"] = {}
    for target in ["ozone", "uv"]:
        fm = final_models[target]
        results["explainability_validation"][target] = explain(fm["model"], va[fm["features"]].reset_index(drop=True),
                                                               va[f"y_{target}"].to_numpy(), target, fm["features"])

    # ------------------------------------------------------------- prediction quality evidence
    from ml.quality import distance_to_training_km
    hold = ho_test.groupby("location_id")[["lat", "lon"]].first()
    pq = {}
    for lid, r in hold.iterrows():
        pq[lid] = {"distance_to_nearest_training_point_km": round(distance_to_training_km(r.lat, r.lon), 1),
                   "ozone_mae": results["spatial_holdout_test"]["ozone"]["by_location"][lid]["mae"],
                   "uv_mae": results["spatial_holdout_test"]["uv"]["by_location"][lid]["mae"]}
    results["prediction_quality_evidence"] = pq
    results["total_runtime_seconds"] = round(time.perf_counter() - t_all, 1)
    save_artifacts(final_models, results, clim, tr, va, te)
    return results


def save_artifacts(final_models, results, clim, tr, va, te) -> None:
    config.MODELS_XGBOOST.mkdir(parents=True, exist_ok=True)
    for target in ["ozone", "uv"]:
        fm = final_models[target]
        joblib.dump(fm["model"], config.MODELS_XGBOOST / f"{target}_model.joblib", compress=3)
        # Portable copy for serving: the pickle above may not open on another OS / Python.
        native = config.MODELS_XGBOOST / f"{target}_model.json"
        if fm["family"] == "XGBoost" and hasattr(fm["model"], "save_model"):
            fm["model"].save_model(native)
        else:
            native.unlink(missing_ok=True)   # never leave a stale file from an earlier run
    clim.to_parquet(config.MODELS / "climatology.parquet", index=False)
    schema = {t: {"features": final_models[t]["features"], "target": config.TARGETS[t],
                  "unit": "µg/m³ (surface ozone mass concentration)" if t == "ozone" else "UV index (dimensionless, WHO scale)"}
              for t in ["ozone", "uv"]}
    schema["uv"]["uses_predicted_ozone"] = bool(final_models["uv"].get("uses_predicted_ozone"))
    schema["horizons"] = config.HORIZONS
    schema["available_at_prediction_time"] = "all features; see docs/data-leakage-audit.md"
    (config.MODELS_XGBOOST / "feature_schema.json").write_text(json.dumps(schema, indent=2))
    conf = {t: final_models[t]["conformal"] for t in ["ozone", "uv"]}
    (config.MODELS_XGBOOST / "conformal.json").write_text(json.dumps(conf, indent=2))
    meta = {
        "model_version": config.MODEL_VERSION,
        "dataset_version": config.DATASET_VERSION,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "forecast_formulation": "direct multi-horizon (lead_h feature), 1-24 h, hourly",
        "training_period_issue_time_utc": [tr["issue_time"].min().isoformat(), tr["issue_time"].max().isoformat()],
        "validation_period_issue_time_utc": [va["issue_time"].min().isoformat(), va["issue_time"].max().isoformat()],
        "test_period_issue_time_utc": [te["issue_time"].min().isoformat(), te["issue_time"].max().isoformat()],
        "training_locations": [l[0] for l in config.LOCATIONS if l[5] == "train"],
        "spatial_holdout_locations": [l[0] for l in config.LOCATIONS if l[5] == "spatial_holdout"],
        "models": {t: {"algorithm": final_models[t]["family"], "hyperparameters": _params(final_models[t]["model"]),
                       "target": config.TARGETS[t], "n_features": len(final_models[t]["features"])}
                   for t in ["ozone", "uv"]},
        "uncertainty": "split-conformal (Mondrian by lead bucket × predicted-value bin), 90 % nominal, calibrated on validation period",
        "validation_metrics": {t: results[t]["models_validation"][results[t]["selected_family"]] for t in ["ozone", "uv"]},
        "test_metrics": {t: results["test"][t]["model"] for t in ["ozone", "uv"]},
        "data_sources": [
            "CAMS global atmospheric composition forecasts (ECMWF/Copernicus) via Open-Meteo Air Quality API (CC BY 4.0)",
            "Archived NWP forecasts via Open-Meteo Historical Forecast API, best_match (CC BY 4.0)",
            "Solar geometry: NOAA solar position equations (computed)",
        ],
    }
    (config.MODELS_XGBOOST / "model_metadata.json").write_text(json.dumps(meta, indent=2, default=str))
    (config.MODELS_XGBOOST / "metrics.json").write_text(json.dumps(results, indent=2, default=str))


def _params(model) -> dict:
    try:
        p = model.get_params()
    except Exception:
        return {}
    return {k: v for k, v in p.items() if isinstance(v, (int, float, str, bool, type(None)))}


def explain_only() -> None:
    """Recompute the explainability block for the saved models (no retraining)."""
    M = json.loads((config.MODELS_XGBOOST / "metrics.json").read_text())
    schema = json.loads((config.MODELS_XGBOOST / "feature_schema.json").read_text())
    va = pd.read_parquet(config.PROCESSED / "val.parquet").dropna(subset=["y_ozone", "y_uv"]).reset_index(drop=True)
    oz = joblib.load(config.MODELS_XGBOOST / "ozone_model.joblib")
    va["pred_ozone"] = postprocess("ozone", oz.predict(va[schema["ozone"]["features"]]), va)
    M["explainability_validation"] = {}
    for t in ["ozone", "uv"]:
        feats = schema[t]["features"]
        model = joblib.load(config.MODELS_XGBOOST / f"{t}_model.joblib")
        M["explainability_validation"][t] = explain(model, va[feats], va[f"y_{t}"].to_numpy(), t, feats)
    (config.MODELS_XGBOOST / "metrics.json").write_text(json.dumps(M, indent=2, default=str))
    print("explainability updated")


if __name__ == "__main__":
    import sys
    explain_only() if "--explain-only" in sys.argv else run()
