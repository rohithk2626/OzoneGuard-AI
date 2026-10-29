"""Usage (from the project folder):
    python -m ml.experiments.coast_distance
    python -m ml.experiments.extra_factors <path to ozoneguard_boundary_layer_height.csv>

Does boundary layer height (BLH) or distance to the sea improve the OzoneGuard models?

Fair comparison: every variant is trained on the SAME rows (issue time 2 Sep 2024 - 30 Sep 2025,
the period where archived BLH forecasts exist), with the production XGBoost settings, and scored
on the production test year (Oct 2025 - Oct 2026) for the 30 training cities and the 8 unseen cities.
"""
import json, sys, time
import numpy as np
import pandas as pd

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))
from ml import config, features as F
from ml.train_xgboost import make_models, postprocess, metrics

BLH_CSV = sys.argv[1]  # path to ozoneguard_boundary_layer_height.csv
SCR = sys.argv[2] if len(sys.argv) > 2 else "docs/experiments"
N_TRAIN = 400_000
RS = config.RANDOM_STATE

# ---- extra factors -----------------------------------------------------------------
blh = pd.read_csv(BLH_CSV)
blh["time_utc"] = pd.to_datetime(blh["time_utc"], utc=True)
blh = blh.set_index(["location_id", "time_utc"])["wx_boundary_layer_height"]
coast = json.load(open(f"{SCR}/coast_km.json"))


def add_extra(df: pd.DataFrame) -> pd.DataFrame:
    tt = pd.to_datetime(df["target_time"], utc=True)
    key = pd.MultiIndex.from_arrays([df["location_id"], tt])
    df = df.assign(fc_boundary_layer_height=blh.reindex(key).to_numpy(),
                   coast_km=df["location_id"].map(coast).to_numpy())
    # mixing depth 6 h earlier than target (captures the night-time collapse / morning growth)
    key6 = pd.MultiIndex.from_arrays([df["location_id"], tt - pd.Timedelta(hours=6)])
    df["fc_blh_minus6h"] = blh.reindex(key6).to_numpy()
    return df


P = config.PROCESSED
val = pd.read_parquet(P / "val.parquet")
test = pd.read_parquet(P / "test.parquet")
hold = pd.read_parquet(P / "spatial_holdout.parquet")
hold = hold[hold["split"] == "holdout_test"]

start = pd.Timestamp("2024-09-02T00:00:00Z")
tr = val[pd.to_datetime(val["issue_time"], utc=True) >= start]
tr = tr.dropna(subset=["y_ozone", "y_uv"])
tr = tr.sample(min(N_TRAIN, len(tr)), random_state=RS).reset_index(drop=True)
tr, test, hold = add_extra(tr), add_extra(test.dropna(subset=["y_ozone", "y_uv"])), add_extra(hold.dropna(subset=["y_ozone", "y_uv"]))
print("train rows", len(tr), tr["issue_time"].min(), tr["issue_time"].max())
print("missing BLH share  train %.4f test %.4f holdout %.4f" % tuple(d["fc_boundary_layer_height"].isna().mean() for d in (tr, test, hold)))

BLH = ["fc_boundary_layer_height", "fc_blh_minus6h"]
variants = {
    "A_current_factors": [],
    "B_plus_boundary_layer": BLH,
    "C_plus_coast_distance": ["coast_km"],
    "D_plus_both": BLH + ["coast_km"],
}
base = {"ozone": F.OZONE_FEATURES, "uv": F.UV_FEATURES_NO_OZONE}
factory = make_models(1)["XGBoost"]
res = {}
for target in ("ozone", "uv"):
    for name, extra in variants.items():
        feats = base[target] + extra
        t0 = time.perf_counter()
        m = factory()
        m.fit(tr[feats], tr[f"y_{target}"])
        r = {"train_s": round(time.perf_counter() - t0)}
        for lab, d in (("test_30_cities", test), ("unseen_8_cities", hold)):
            p = postprocess(target, m.predict(d[feats]), d[feats])
            r[lab] = metrics(d[f"y_{target}"].to_numpy(), p)
            # night-time vs day-time split for ozone (where mixing should matter most)
            if target == "ozone":
                day = d["solar_elevation"].to_numpy() > 0
                r[lab]["mae_day"] = metrics(d[f"y_{target}"].to_numpy()[day], p[day])["mae"]
                r[lab]["mae_night"] = metrics(d[f"y_{target}"].to_numpy()[~day], p[~day])["mae"]
        if extra:
            imp = dict(zip(feats, m.feature_importances_))
            r["gain_share_of_new_factors"] = {f: round(float(imp[f]), 4) for f in extra}
        res.setdefault(target, {})[name] = r
        print(target, name, json.dumps({k: (v if not isinstance(v, dict) else {kk: round(vv, 3) if isinstance(vv, float) else vv for kk, vv in v.items()}) for k, v in r.items()}), flush=True)
        json.dump(res, open(f"{SCR}/experiment_results.json", "w"), indent=1)
