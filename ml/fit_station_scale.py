"""Fit the "station-equivalent" scale for forecast ozone.

The forecast models learn CAMS surface ozone, which over India reads several times higher than
CPCB monitoring stations (docs/ground-truth-validation.md). This script fits one multiplicative
factor, station ≈ factor × CAMS, from hourly station data and the CAMS values for the same places
and hours, and writes it to models/station_scale.json, where the backend picks it up.

Why one factor: on the 2025 data from seven CPCB stations, a single ratio predicted a station it had
not been fitted on as well as a factor per hour of day, per month, a straight-line fit or quantile
mapping did (leave-one-station-out). It is also the method a published comparison of reanalysis
ozone with CPCB stations found best (ratio adjustment; Earth Systems and Environment, 2025).

    python -m ml.fit_station_scale data/external/stations data/validation/cams_ozone_at_stations_2025.csv

The CAMS file needs the columns station, time_utc, cams_ozone, with station names as the ground-truth
check derives them from the station file names (e.g. "sirifort delhi cpcb").
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from ml import config
from ml import validate_ground_truth as gt

OUT = config.MODELS / "station_scale.json"


def matched_hours(station_paths: list[Path], cams_csv: Path) -> pd.DataFrame:
    """Hourly station ozone and CAMS ozone for the same station and UTC hour (station data cleaned)."""
    frames = []
    for f in gt.expand_station_paths(station_paths):
        s, _ = gt.clean_station(gt.read_station_file(f))
        frames.append(s)
    st = pd.concat(frames, ignore_index=True)
    cams = pd.read_csv(cams_csv)
    cams["time_utc"] = pd.to_datetime(cams["time_utc"], utc=True)
    d = st.merge(cams[["station", "time_utc", "cams_ozone"]], on=["station", "time_utc"], how="inner")
    return d.dropna(subset=["station_ozone", "cams_ozone"])


def ratio(d: pd.DataFrame) -> float:
    return float(d["station_ozone"].sum() / d["cams_ozone"].sum())


def leave_one_station_out(d: pd.DataFrame) -> dict:
    """Fit on all stations but one, score on the one left out; repeat for each station."""
    per = {}
    for held in sorted(d["station"].unique()):
        tr, te = d[d["station"] != held], d[d["station"] == held]
        k = ratio(tr)
        before = te["cams_ozone"] - te["station_ozone"]
        after = k * te["cams_ozone"] - te["station_ozone"]
        per[held] = {"hours": int(len(te)), "mae_before": round(float(before.abs().mean()), 1),
                     "mae_after": round(float(after.abs().mean()), 1), "bias_after": round(float(after.mean()), 1),
                     "factor_without_this_station": round(k, 4)}
    mean = lambda key: round(float(np.mean([v[key] for v in per.values()])), 1)
    return {"mae_before": mean("mae_before"), "mae_after": mean("mae_after"), "bias_after": mean("bias_after"),
            "worst_station_mae_after": max(v["mae_after"] for v in per.values()), "per_station": per}


def fit(d: pd.DataFrame) -> dict:
    t = d["time_utc"]
    return {
        "factor": round(ratio(d), 4),
        "method": "single multiplicative ratio: sum(station ozone) / sum(CAMS ozone) over all matched hours",
        "fitted_on": {"stations": sorted(d["station"].unique().tolist()), "matched_hours": int(len(d)),
                      "period_utc": [t.min().isoformat(), t.max().isoformat()],
                      "station_mean": round(float(d["station_ozone"].mean()), 1),
                      "cams_mean": round(float(d["cams_ozone"].mean()), 1)},
        "per_station_ratio": {s: round(ratio(g), 4) for s, g in d.groupby("station")},
        "leave_one_station_out": leave_one_station_out(d),
        "meaning": ("Approximate ozone a typical CPCB city monitoring station would report. Fitted on a few stations, "
                    "so it is an estimate: compared with a station it was not fitted on it was off by about the "
                    "'mae_after' value on average. Applies to surface ozone only, not to UV."),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("stations", type=Path, help="folder (or files) of CPCB station data, as for ml.validate_ground_truth")
    ap.add_argument("cams_csv", type=Path, help="CSV with station, time_utc, cams_ozone for the same stations and period")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    d = matched_hours([args.stations], args.cams_csv)
    if d.empty:
        ap.error("no station hours matched the CAMS file; check that the station names agree")
    result = fit(d)
    args.out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    lo = result["leave_one_station_out"]
    print(f"factor {result['factor']}  ({result['fitted_on']['matched_hours']:,} hours, {len(result['fitted_on']['stations'])} stations)")
    print(f"leave-one-station-out MAE: {lo['mae_before']} -> {lo['mae_after']} µg/m³ (bias {lo['bias_after']:+})")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
