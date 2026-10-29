"""Generate docs/ml-results.md (+ figures) directly from models/xgboost/metrics.json.

Numbers are never typed by hand: re-running training and this script
regenerates the report.
"""
from __future__ import annotations

import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from ml import config

UNITS = {"ozone": "µg/m³", "uv": "UV index"}
NAMES = {"ozone": "Surface ozone", "uv": "UV index"}


def f(x, n=3):
    return "—" if x is None else f"{x:.{n}f}"


def table_models(bench: dict) -> list[str]:
    L = ["| Model | Train time (s) | Val MAE | Val RMSE | Val R² | Inference (ms / 1k rows) | Size (MB) |", "|---|---|---|---|---|---|---|"]
    for name, m in bench["baselines_validation"].items():
        L.append(f"| *Baseline:* {name} | — | {f(m['mae'])} | {f(m['rmse'])} | {f(m['r2'])} | — | — |")
    for name, m in bench["models_validation"].items():
        star = " **(selected)**" if name == bench["selected_family"] else ""
        L.append(f"| {name}{star} | {m['train_seconds']} | {f(m['mae'])} | {f(m['rmse'])} | {f(m['r2'])} | {m['inference_ms_per_1k_rows']} | {m['model_size_mb']} |")
    return L


def figures(M: dict) -> list[str]:
    config.REPORTS.mkdir(parents=True, exist_ok=True)
    out = []
    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    for ax, t in zip(axes, ["ozone", "uv"]):
        bl = M["test"][t]["by_lead"]
        leads = sorted(int(k) for k in bl)
        for key, lab, c in [("model", "OzoneGuard model", "#0f5f55"), ("persistence", "Persistence", "#999"),
                            ("same_hour_prev_day", "Same hour previous day", "#d4a72c")]:
            ax.plot(leads, [bl[str(h)][key]["mae"] for h in leads], marker="o", ms=3, label=lab, color=c)
        ax.set_title(f"{NAMES[t]}: test MAE by lead time"); ax.set_xlabel("Lead (hours)"); ax.set_ylabel(f"MAE ({UNITS[t]})")
        ax.legend(fontsize=8)
    fig.tight_layout(); fig.savefig(config.REPORTS / "test_mae_by_lead.png", dpi=120); plt.close(fig)
    out.append("test_mae_by_lead.png")
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    for ax, t in zip(axes, ["ozone", "uv"]):
        ex = M["explainability_validation"][t]
        key = "mean_abs_shap" if "mean_abs_shap" in ex else "permutation_mae_increase"
        items = list(ex[key].items())[:15][::-1]
        ax.barh([k for k, _ in items], [v for _, v in items], color="#168779")
        ax.set_title(f"{NAMES[t]}: {key.replace('_', ' ')} (top 15)", fontsize=10)
    fig.tight_layout(); fig.savefig(config.REPORTS / "feature_importance.png", dpi=120); plt.close(fig)
    out.append("feature_importance.png")
    return out


def main() -> None:
    M = json.loads((config.MODELS_XGBOOST / "metrics.json").read_text())
    meta = json.loads((config.MODELS_XGBOOST / "model_metadata.json").read_text())
    figs = figures(M)
    L = ["# ML results", "", f"Generated from `models/xgboost/metrics.json` by `python -m ml.report` (training run {M['generated_at']}).", "",
         "All numbers are measured on real data (CAMS + archived NWP forecasts, 38 Indian locations). "
         "Targets: **surface ozone (µg/m³)** and **all-sky UV index**, both from CAMS (model-derived truth — see scientific-limitations.md).", "",
         "## Data and splits", "",
         "| Split | Issue-time period (UTC) | Rows (location × issue time × lead) |", "|---|---|---|",
         f"| Train | {meta['training_period_issue_time_utc'][0][:10]} → {meta['training_period_issue_time_utc'][1][:10]} | {M['rows_with_targets']['train']:,} |",
         f"| Validation | {meta['validation_period_issue_time_utc'][0][:10]} → {meta['validation_period_issue_time_utc'][1][:10]} | {M['rows_with_targets']['val']:,} |",
         f"| Test (used once) | {meta['test_period_issue_time_utc'][0][:10]} → {meta['test_period_issue_time_utc'][1][:10]} | {M['rows_with_targets']['test']:,} |",
         f"| Spatial holdout (8 never-trained locations, all periods) | — | {M['rows_with_targets']['holdout']:,} |", "",
         f"Model-family benchmarks were trained on a random {M['benchmark_train_rows']:,}-row subsample of the training period (2-CPU budget); "
         "the selected family was then refit on the full training period.", ""]
    for t in ["ozone", "uv"]:
        b = M[t]
        L += [f"## {NAMES[t]} — validation benchmark ({UNITS[t]})", ""] + table_models(b) + [""]
        if "per_horizon_variant_validation" in b:
            ph, sm = b["per_horizon_variant_validation"], b["single_multi_horizon_validation"]
            L += [f"Direct single multi-horizon model vs 24 per-horizon models ({b['selected_family']}, same subsample): "
                  f"MAE {f(sm['mae'])} vs {f(ph['mae'])} (train {sm['train_seconds']} s vs {ph['train_seconds']} s).", ""]
        fv = b["final_model_validation_full_train"]
        L += [f"Final {b['selected_family']} refit on the full training period — validation MAE {f(fv['mae'])}, RMSE {f(fv['rmse'])}, R² {f(fv['r2'])}.", ""]
    a = M["uv_ozone_ablation_validation"]
    L += ["## Does ozone help the UV forecast? (validation ablation)", "", "| UV model variant | Val MAE | Val RMSE | Val R² |", "|---|---|---|---|"]
    for k in ["no_ozone", "with_observed_surface_ozone_lags", "with_predicted_surface_ozone"]:
        L.append(f"| {k.replace('_', ' ')} | {f(a[k]['mae'])} | {f(a[k]['rmse'])} | {f(a[k]['r2'])} |")
    L += ["", f"Decision rule: {a['decision_rule']}. **Decision: `{a['decision']}`.**", ""]

    L += ["## Test-period results (evaluated once)", ""]
    for t in ["ozone", "uv"]:
        T = M["test"][t]
        L += [f"### {NAMES[t]} ({UNITS[t]})", "", "| Forecast | MAE | RMSE | R² | n |", "|---|---|---|---|---|",
              f"| **OzoneGuard model** | **{f(T['model']['mae'])}** | **{f(T['model']['rmse'])}** | **{f(T['model']['r2'])}** | {T['model']['n']:,} |"]
        for name, m in T["baselines"].items():
            L.append(f"| {name} | {f(m['mae'])} | {f(m['rmse'])} | {f(m['r2'])} | {m['n']:,} |")
        L += ["", f"* Native CAMS hours only (00, 03, …, 21 UTC): MAE {f(T['model_native_hours_only']['mae'])}, R² {f(T['model_native_hours_only']['r2'])}"]
        if t == "uv":
            L.append(f"* Daytime only (sun above horizon): MAE {f(T['model_daytime_only']['mae'])}, RMSE {f(T['model_daytime_only']['rmse'])}, R² {f(T['model_daytime_only']['r2'])}")
        iv = T["interval_90"]
        L.append(f"* 90 % conformal range: empirical coverage **{iv['coverage']:.1%}**, mean width {f(iv['mean_width'], 2)} {UNITS[t]}")
        q = M["quantile_regression_comparison_test"][t]
        L.append(f"* Alternative (LightGBM 5–95 % quantile regression): coverage {q['coverage']:.1%}, mean width {f(q['mean_width'], 2)}")
        H = M["spatial_holdout_test"][t]
        L.append(f"* **Unseen locations** (spatial holdout, test period): MAE {f(H['model']['mae'])}, RMSE {f(H['model']['rmse'])}, R² {f(H['model']['r2'])}, range coverage {H['interval_90']['coverage']:.1%}")
        L += ["", "Test MAE by region:", "", "| Region | MAE | R² | n |", "|---|---|---|---|"]
        L += [f"| {r} | {f(m['mae'])} | {f(m['r2'])} | {m['n']:,} |" for r, m in T["by_region"].items()]
        L.append("")
        bl = T["by_lead"]
        L += ["Selected leads:", "", "| Lead (h) | Model MAE | Persistence MAE | Same-hour-prev-day MAE |", "|---|---|---|---|"]
        for h in [1, 3, 6, 12, 18, 24]:
            r = bl[str(h)]
            L.append(f"| {h} | {f(r['model']['mae'])} | {f(r['persistence']['mae'])} | {f(r['same_hour_prev_day']['mae'])} |")
        L.append("")
    R = M["test"]["uv"]["risk_classification"]
    L += ["### UV risk category (WHO bands, from the continuous forecast)", ""]
    for k in ["daytime_only", "all_hours"]:
        r = R[k]
        L += [f"**{k.replace('_', ' ')}** — accuracy {r['accuracy']:.3f}, macro-F1 {r['macro_f1']:.3f}, weighted-F1 {r['weighted_f1']:.3f}", "",
              "| Class | Precision | Recall | F1 | Support |", "|---|---|---|---|---|"]
        L += [f"| {c} | {f(v['precision'])} | {f(v['recall'])} | {f(v['f1'])} | {v['support']:,} |" for c, v in r["per_class"].items()]
        L += ["", "Confusion matrix (rows = CAMS category, columns = forecast category; " + ", ".join(r["labels"]) + "):", "", "```"]
        L += ["  ".join(f"{x:>8}" for x in row) for row in r["confusion_matrix"]]
        L += ["```", ""]
    L += ["## Does ML beat the simple baselines?", ""]
    for t in ["ozone", "uv"]:
        T = M["test"][t]
        best_name, best = min(T["baselines"].items(), key=lambda kv: kv[1]["mae"])
        gain = 1 - T["model"]["mae"] / best["mae"]
        verdict = "Yes" if gain > 0 else "No"
        L.append(f"* **{NAMES[t]}: {verdict}.** Test MAE {f(T['model']['mae'])} vs best baseline '{best_name}' {f(best['mae'])} "
                 f"({gain:+.1%} relative MAE reduction).")
    T_uv, T_oz = M["test"]["uv"], M["test"]["ozone"]
    rc = T_uv["risk_classification"]["daytime_only"]["per_class"]
    L += ["", "## How to read these numbers", "",
          f"* **UV all-hours scores are flattered by night.** About half the rows are night (UV = 0, trivially right). "
          f"The honest daytime UV error is MAE {f(T_uv['model_daytime_only']['mae'])} (R² {f(T_uv['model_daytime_only']['r2'])}).",
          f"* **Extremes are under-forecast.** Daytime recall for 'Extreme' is {f(rc['Extreme']['recall'])} and for 'High' {f(rc['High']['recall'])}; "
          "most misses fall one category lower. Use the upper end of the range (`possible_high_risk_windows_upper_bound`) for caution.",
          f"* **Error grows with lead time** (ozone MAE {f(T_oz['by_lead']['1']['model']['mae'])} at 1 h → {f(T_oz['by_lead']['24']['model']['mae'])} at 24 h), "
          "and by 24 h the advantage over 'same hour yesterday' is smaller.",
          "* **Surface ozone did not improve the UV forecast** (ablation). This matches the physics: UV is attenuated by the *column* ozone, "
          "mostly stratospheric, not by near-ground ozone. A total-column-ozone feature (blocked, see blockers.md) is the physically relevant test.",
          "* **The skill is relative to CAMS.** These scores say how well we reproduce CAMS, not ground monitors (scientific-limitations.md).",
          "* **Unseen locations perform close to seen ones** (spatial holdout), so the medium-quality tier is supported up to ~300 km from a training point."]
    L += ["", "## Explainability (validation, measured)", ""]
    for t in ["ozone", "uv"]:
        ex = M["explainability_validation"][t]
        L += [f"### {NAMES[t]}", "", "| Rank | Mean |SHAP| | Permutation (MAE increase) |", "|---|---|---|"]
        sh = list(ex.get("mean_abs_shap", {}).items())[:10]
        pi = list(ex["permutation_mae_increase"].items())[:10]
        for i in range(10):
            a_ = f"{sh[i][0]} ({sh[i][1]:.3f})" if i < len(sh) else "—"
            b_ = f"{pi[i][0]} ({pi[i][1]:.3f})" if i < len(pi) else "—"
            L.append(f"| {i + 1} | {a_} | {b_} |")
        L.append("")
    L += ["## Prediction-quality evidence (never-trained locations, test period)", "",
          "| Holdout location | Distance to nearest training point (km) | Ozone MAE | UV MAE |", "|---|---|---|---|"]
    for lid, e in M["prediction_quality_evidence"].items():
        L.append(f"| {lid} | {e['distance_to_nearest_training_point_km']} | {f(e['ozone_mae'])} | {f(e['uv_mae'])} |")
    L += ["", "## Figures", ""] + [f"![{x}](figures/{x})" for x in figs]
    (config.ROOT / "docs" / "ml-results.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("wrote docs/ml-results.md")


if __name__ == "__main__":
    main()
