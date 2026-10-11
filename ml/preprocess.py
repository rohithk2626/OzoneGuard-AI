"""Quality control + spatiotemporal alignment.

Input : data/raw/openmeteo/<location>.parquet   (raw API values, UTC)
Output: data/intermediate/cleaned.parquet        (one row per location-hour)
        data/intermediate/quality_report.json
        docs/data-quality-report.md

Alignment (see docs/prediction-pipeline.md for the full METHOD/REASON/
ASSUMPTION/LIMITATION table):
* Spatial: each requested coordinate is mapped by the provider to its nearest
  native grid cell (CAMS ~0.4°, NWP model cell). No interpolation is applied.
  The grid-cell offset (km) is recorded per location.
* Temporal: both sources are requested in UTC ("timezone=GMT") on the same
  hourly axis and joined on the exact timestamp. No resampling.
* CAMS global native output is 3-hourly; Open-Meteo serves hourly values.
  We test empirically whether the in-between hours are interpolated and flag
  native timestamps (``cams_native``) so evaluation can be reported on native
  hours only.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from ml import config
from ml.solar import solar_position


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def load_raw(raw_dir: Path = config.RAW_OPENMETEO) -> pd.DataFrame:
    files = sorted(raw_dir.glob("*.parquet"))
    if not files:
        raise FileNotFoundError(f"No raw parquet files in {raw_dir}. Run ml.collect_data first.")
    df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    df["time_utc"] = pd.to_datetime(df["time_utc"], utc=True)
    return df


def interpolation_test(df: pd.DataFrame, col: str) -> dict:
    """Fraction of non-native hours that equal the linear interpolation of the
    surrounding native (hour % 3 == 0) values, within rounding tolerance."""
    res = []
    for _, g in df.groupby("location_id"):
        s = g.set_index("time_utc")[col].sort_index()
        native = s[s.index.hour % 3 == 0]
        interp = native.reindex(s.index).interpolate(method="time", limit_area="inside")
        nn = s.index.hour % 3 != 0
        a, b = s[nn], interp[nn]
        ok = a.notna() & b.notna()
        tol = 0.051 if col.endswith("uv_index") or "uv" in col else 0.51
        res.append(((a[ok] - b[ok]).abs() <= tol).mean())
    return {"column": col, "share_non_native_hours_equal_to_linear_interp": float(np.nanmean(res))}


def clean(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    report: dict = {"rows_raw": int(len(df))}

    # Duplicates --------------------------------------------------------------
    dup = df.duplicated(["location_id", "time_utc"]).sum()
    report["duplicate_rows_removed"] = int(dup)
    df = df.drop_duplicates(["location_id", "time_utc"]).copy()

    # Coordinates -------------------------------------------------------------
    bad_coord = ~df["req_lat"].between(-90, 90) | ~df["req_lon"].between(-180, 180)
    report["invalid_coordinate_rows"] = int(bad_coord.sum())
    df = df[~bad_coord]

    # Timestamps: complete hourly grid per location ----------------------------
    full = []
    gaps = {}
    for lid, g in df.groupby("location_id"):
        idx = pd.date_range(g["time_utc"].min(), g["time_utc"].max(), freq="h", tz="UTC")
        gaps[lid] = int(len(idx) - len(g))
        g = g.set_index("time_utc").reindex(idx)
        g.index.name = "time_utc"
        meta = [c for c in g.columns if c not in config.PHYSICAL_LIMITS]
        g[meta] = g[meta].ffill().bfill()
        full.append(g.reset_index())
    df = pd.concat(full, ignore_index=True)
    report["missing_timestamps_inserted"] = gaps

    # Physical limits -----------------------------------------------------------
    limits = {}
    for col, (lo, hi) in config.PHYSICAL_LIMITS.items():
        if col not in df:
            continue
        bad = df[col].notna() & ~df[col].between(lo, hi)
        limits[col] = int(bad.sum())
        df.loc[bad, col] = np.nan
    report["values_outside_physical_limits_set_nan"] = limits

    # Missingness ---------------------------------------------------------------
    report["missing_share"] = {c: round(float(df[c].isna().mean()), 5) for c in config.PHYSICAL_LIMITS if c in df}
    first_valid = df.dropna(subset=["cams_ozone"]).groupby("location_id")["time_utc"].min()
    report["first_valid_cams_time"] = {k: v.isoformat() for k, v in first_valid.items()}

    # Solar geometry + physical consistency of UV ------------------------------------
    sp = solar_position(df["time_utc"], df["req_lat"].to_numpy(), df["req_lon"].to_numpy())
    df["solar_elevation"] = sp["solar_elevation"]
    night = df["solar_elevation"] < -1.0
    for col in ["cams_uv_index", "wx_uv_index"]:
        report[f"{col}_positive_at_night_share"] = float((df.loc[night, col] > 0.05).mean())
    report["corr_cams_uv_vs_cos_zenith"] = float(df[["cams_uv_index"]].assign(c=sp["cos_zenith"]).corr().iloc[0, 1])

    # Native CAMS timestamps -------------------------------------------------------
    df["cams_native"] = df["time_utc"].dt.hour % 3 == 0
    report["interpolation_tests"] = [interpolation_test(df, c) for c in ["cams_ozone", "cams_uv_index", "wx_temperature_2m"]]

    # Spatial alignment offsets ------------------------------------------------------
    loc = df.groupby("location_id").first()
    offsets = {}
    for lid, r in loc.iterrows():
        offsets[lid] = {
            "cams_cell_offset_km": round(haversine_km(r.req_lat, r.req_lon, r.aq_lat, r.aq_lon), 1),
            "nwp_cell_offset_km": round(haversine_km(r.req_lat, r.req_lon, r.wx_lat, r.wx_lon), 1),
            "cams_cell": [float(r.aq_lat), float(r.aq_lon)],
            "nwp_cell": [float(r.wx_lat), float(r.wx_lon)],
            "elevation_m": float(r.wx_elev) if pd.notna(r.wx_elev) else None,
        }
    report["spatial_alignment"] = offsets

    # Drop rows before CAMS starts (provider has no data there) ----------------------
    df = df[df["time_utc"] >= pd.Timestamp(config.START_DATE, tz="UTC")]
    report["rows_clean"] = int(len(df))
    report["date_range"] = [df["time_utc"].min().isoformat(), df["time_utc"].max().isoformat()]
    report["locations"] = int(df["location_id"].nunique())
    report["rows_by_region"] = df.groupby("region").size().astype(int).to_dict()
    return df.sort_values(["location_id", "time_utc"]).reset_index(drop=True), report


def write_markdown(report: dict, path: Path) -> None:
    lines = ["# Data quality report", "", "Generated by `python -m ml.preprocess` from the raw Open-Meteo extracts.", "",
             f"* Raw rows: **{report['rows_raw']:,}**  ·  clean rows: **{report['rows_clean']:,}**",
             f"* Locations: **{report['locations']}**  ·  period (UTC): {report['date_range'][0]} → {report['date_range'][1]}",
             f"* Duplicate rows removed: {report['duplicate_rows_removed']}",
             f"* Invalid coordinates: {report['invalid_coordinate_rows']}",
             f"* Missing hourly timestamps inserted (total): {sum(report['missing_timestamps_inserted'].values())}",
             "", "## Values outside physical limits (set to NaN, not deleted rows)", "", "| Column | Count |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in report["values_outside_physical_limits_set_nan"].items()]
    lines += ["", "## Missing share per column", "", "| Column | Missing share |", "|---|---|"]
    lines += [f"| {k} | {v:.3%} |" for k, v in report["missing_share"].items()]
    lines += ["", "## Physical consistency", "",
              f"* CAMS UV > 0.05 while the sun is >1° below the horizon: {report['cams_uv_index_positive_at_night_share']:.3%} of night hours",
              f"* NWP UV > 0.05 at night: {report['wx_uv_index_positive_at_night_share']:.3%} of night hours",
              f"* Pearson r(CAMS UV, cos solar zenith): {report['corr_cams_uv_vs_cos_zenith']:.3f}",
              "", "## Native vs interpolated hours", "",
              "CAMS global is produced 3-hourly. Share of non-native hours that equal linear interpolation of the neighbouring native values:", ""]
    lines += [f"* `{t['column']}`: {t['share_non_native_hours_equal_to_linear_interp']:.1%}" for t in report["interpolation_tests"]]
    lines += ["", "## Rows by region", "", "| Region | Rows |", "|---|---|"]
    lines += [f"| {k} | {v:,} |" for k, v in report["rows_by_region"].items()]
    lines += ["", "## Spatial alignment (requested point → provider grid cell)", "",
              "| Location | CAMS cell | offset km | NWP cell | offset km | elevation m |", "|---|---|---|---|---|---|"]
    for lid, o in report["spatial_alignment"].items():
        lines.append(f"| {lid} | {o['cams_cell'][0]:.2f}, {o['cams_cell'][1]:.2f} | {o['cams_cell_offset_km']} | "
                     f"{o['nwp_cell'][0]:.3f}, {o['nwp_cell'][1]:.3f} | {o['nwp_cell_offset_km']} | {o['elevation_m']} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    raw = load_raw()
    df, report = clean(raw)
    config.INTERMEDIATE.mkdir(parents=True, exist_ok=True)
    df.to_parquet(config.INTERMEDIATE / "cleaned.parquet", index=False)
    (config.INTERMEDIATE / "quality_report.json").write_text(json.dumps(report, indent=2, default=str))
    write_markdown(report, config.ROOT / "docs" / "data-quality-report.md")
    print(json.dumps({k: report[k] for k in ["rows_raw", "rows_clean", "locations", "date_range"]}, indent=2))


if __name__ == "__main__":
    main()
