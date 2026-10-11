"""Correlation analysis (PAST): measured relationships in the cleaned hourly data.

python -m ml.correlation  ->  docs/correlation-analysis.md + docs/figures/*.png

Correlation is not causation. Diurnal and seasonal cycles drive many of these
coefficients (both variables follow the sun), so daytime-only and
deseasonalised (anomaly) correlations are reported as well.
"""
from __future__ import annotations

import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from ml import config
from ml.solar import solar_position

PAIRS = [
    ("cams_ozone", "cams_uv_index"), ("cams_ozone", "wx_temperature_2m"), ("cams_ozone", "wx_relative_humidity_2m"),
    ("cams_ozone", "wx_wind_speed_10m"), ("cams_ozone", "wx_cloud_cover"), ("cams_ozone", "wx_precipitation"),
    ("cams_ozone", "wx_shortwave_radiation"), ("cams_uv_index", "wx_cloud_cover"), ("cams_uv_index", "solar_elevation"),
    ("cams_uv_index", "season_cos_doy"), ("cams_ozone", "season_cos_doy"), ("cams_ozone", "lat"),
    ("cams_uv_index", "cams_aerosol_optical_depth"), ("cams_ozone", "cams_nitrogen_dioxide"),
]
LABELS = {"cams_ozone": "Surface O₃ (µg/m³)", "cams_uv_index": "UV index", "wx_temperature_2m": "Temperature",
          "wx_relative_humidity_2m": "Rel. humidity", "wx_wind_speed_10m": "Wind speed", "wx_cloud_cover": "Cloud cover",
          "wx_precipitation": "Precipitation", "wx_shortwave_radiation": "Shortwave rad.", "solar_elevation": "Solar elevation",
          "season_cos_doy": "cos(day of year)", "lat": "Latitude", "cams_aerosol_optical_depth": "AOD",
          "cams_nitrogen_dioxide": "NO₂"}
FIG = config.REPORTS


def prepare(clean: pd.DataFrame) -> pd.DataFrame:
    df = clean.copy()
    if "solar_elevation" not in df:
        df["solar_elevation"] = solar_position(df["time_utc"], df["req_lat"].to_numpy(), df["req_lon"].to_numpy())["solar_elevation"]
    df["season_cos_doy"] = np.cos(2 * np.pi * df["time_utc"].dt.dayofyear / 365.25)
    df["lat"] = df["req_lat"]
    df["month"] = df["time_utc"].dt.month
    df["hour"] = df["time_utc"].dt.hour
    # anomaly w.r.t. location × month × hour mean (descriptive, whole period)
    for c in ["cams_ozone", "cams_uv_index", "wx_cloud_cover", "wx_temperature_2m"]:
        df[c + "_anom"] = df[c] - df.groupby(["location_id", "month", "hour"])[c].transform("mean")
    return df


def corr_table(df: pd.DataFrame) -> list[dict]:
    day = df["solar_elevation"] > 5
    out = []
    for a, b in PAIRS:
        row = {"a": a, "b": b}
        for lbl, sub in [("all", df), ("day", df[day])]:
            s = sub[[a, b]].dropna()
            row[f"pearson_{lbl}"] = float(s[a].corr(s[b]))
            row[f"spearman_{lbl}"] = float(s[a].corr(s[b], method="spearman"))
            row[f"n_{lbl}"] = int(len(s))
        if a + "_anom" in df and b + "_anom" in df:
            s = df.loc[day, [a + "_anom", b + "_anom"]].dropna()
            row["pearson_anom_day"] = float(s.iloc[:, 0].corr(s.iloc[:, 1]))
        out.append(row)
    return out


def figures(df: pd.DataFrame) -> list[str]:
    FIG.mkdir(parents=True, exist_ok=True)
    made = []
    cols = ["cams_ozone", "cams_uv_index", "wx_temperature_2m", "wx_relative_humidity_2m", "wx_wind_speed_10m",
            "wx_cloud_cover", "wx_precipitation", "wx_shortwave_radiation", "solar_elevation", "season_cos_doy", "lat",
            "cams_aerosol_optical_depth", "cams_nitrogen_dioxide"]
    for method in ["pearson", "spearman"]:
        c = df[cols].sample(min(len(df), 400_000), random_state=0).corr(method=method)
        fig, ax = plt.subplots(figsize=(10, 8.5))
        im = ax.imshow(c.values, cmap="RdBu_r", vmin=-1, vmax=1)
        ax.set_xticks(range(len(cols)), [LABELS[x] for x in cols], rotation=60, ha="right", fontsize=8)
        ax.set_yticks(range(len(cols)), [LABELS[x] for x in cols], fontsize=8)
        for i in range(len(cols)):
            for j in range(len(cols)):
                ax.text(j, i, f"{c.values[i, j]:.2f}", ha="center", va="center", fontsize=6.5,
                        color="white" if abs(c.values[i, j]) > 0.6 else "black")
        fig.colorbar(im, ax=ax, shrink=0.8)
        ax.set_title(f"{method.title()} correlation matrix (all hours, 38 locations, 2022-08 → 2026-10)")
        fig.tight_layout()
        p = FIG / f"correlation_{method}.png"
        fig.savefig(p, dpi=130)
        plt.close(fig)
        made.append(p.name)

    s = df.sample(min(len(df), 60_000), random_state=1)
    for x, y, name in [("cams_ozone", "cams_uv_index", "scatter_ozone_uv"), ("solar_elevation", "cams_uv_index", "scatter_uv_solar"),
                       ("wx_cloud_cover", "cams_uv_index", "scatter_uv_cloud"), ("wx_temperature_2m", "cams_ozone", "scatter_ozone_temp")]:
        fig, ax = plt.subplots(figsize=(6, 4.5))
        ax.scatter(s[x], s[y], s=2, alpha=0.15, color="#1b6e8a")
        ax.set_xlabel(LABELS[x]); ax.set_ylabel(LABELS[y])
        ax.set_title(f"{LABELS[y]} vs {LABELS[x]} (random 60k hourly samples)", fontsize=9)
        fig.tight_layout(); fig.savefig(FIG / f"{name}.png", dpi=120); plt.close(fig)
        made.append(f"{name}.png")

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.2))
    for ax, col in zip(axes, ["cams_ozone", "cams_uv_index"]):
        m = df[df["solar_elevation"] > 0].groupby(["region", "month"])[col].mean().unstack(0)
        m.plot(ax=ax, marker="o", ms=3)
        ax.set_title(f"Monthly mean daytime {LABELS[col]} by region"); ax.set_xlabel("Month"); ax.set_xticks(range(1, 13))
    fig.tight_layout(); fig.savefig(FIG / "seasonal_by_region.png", dpi=120); plt.close(fig)
    made.append("seasonal_by_region.png")

    fig, ax = plt.subplots(figsize=(7, 4))
    for col, c in [("cams_ozone", "#b5462e")]:
        df.groupby("hour")[col].mean().plot(ax=ax, color=c, label="Surface O₃ (µg/m³)")
    ax2 = ax.twinx()
    df.groupby("hour")["cams_uv_index"].mean().plot(ax=ax2, color="#d4a72c", label="UV index")
    ax.set_xlabel("Hour (UTC; IST = UTC+5:30)"); ax.set_ylabel("Surface O₃"); ax2.set_ylabel("UV index")
    ax.set_title("Mean diurnal cycle, all locations"); fig.legend(loc="upper right"); fig.tight_layout()
    fig.savefig(FIG / "diurnal_cycle.png", dpi=120); plt.close(fig)
    made.append("diurnal_cycle.png")
    return made


def write_doc(rows: list[dict], figs: list[str], n_rows: int) -> None:
    L = ["# Correlation analysis (PAST)", "",
         f"Computed by `python -m ml.correlation` on the cleaned hourly dataset ({n_rows:,} location-hours, 38 locations, "
         "Aug 2022 → Oct 2026, UTC). Values below are measured, not assumed.", "",
         "**Correlation ≠ causation.** Both ozone and UV follow the sun, so the 'all hours' coefficients are dominated by the "
         "shared diurnal cycle. The *daytime* columns restrict to solar elevation > 5°, and the *anomaly* column removes the "
         "location × month × hour mean from both variables (daytime only), which isolates day-to-day co-variation.", "",
         "| Pair | Pearson (all) | Spearman (all) | Pearson (day) | Spearman (day) | Pearson anomaly (day) | n (all) |",
         "|---|---|---|---|---|---|---|"]
    for r in rows:
        an = f"{r['pearson_anom_day']:.3f}" if "pearson_anom_day" in r else "—"
        L.append(f"| {LABELS[r['a']]} ↔ {LABELS[r['b']]} | {r['pearson_all']:.3f} | {r['spearman_all']:.3f} | "
                 f"{r['pearson_day']:.3f} | {r['spearman_day']:.3f} | {an} | {r['n_all']:,} |")
    L += ["", "## Figures", ""] + [f"![{f}](figures/{f})" for f in figs]
    (config.ROOT / "docs" / "correlation-analysis.md").write_text("\n".join(L) + "\n", encoding="utf-8")


def main() -> None:
    clean = pd.read_parquet(config.INTERMEDIATE / "cleaned.parquet")
    df = prepare(clean)
    rows = corr_table(df)
    figs = figures(df)
    (config.INTERMEDIATE / "correlations.json").write_text(json.dumps(rows, indent=2))
    write_doc(rows, figs, len(df))
    for r in rows:
        print(f"{r['a']:28s} {r['b']:30s} P={r['pearson_all']:+.3f} S={r['spearman_all']:+.3f} Pday={r['pearson_day']:+.3f}")


if __name__ == "__main__":
    main()
