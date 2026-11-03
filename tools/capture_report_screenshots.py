"""Capture website screenshots + XGBoost-vs-LSTM chart for the project report.
Run by tools/capture_report_screenshots.bat (server must be on http://127.0.0.1:8765)."""
import json, time, traceback
from pathlib import Path
import requests

BASE = "http://127.0.0.1:8765"
OUT = Path(__file__).resolve().parent.parent / "docs" / "report-screenshots"
OUT.mkdir(parents=True, exist_ok=True)
LOG = OUT / "capture_log.txt"
HYD = {"lat": 17.39, "lon": 78.49, "name": "Hyderabad"}

def log(*a):
    msg = " ".join(str(x) for x in a); print(msg, flush=True)
    with open(LOG, "a", encoding="utf-8") as f: f.write(msg + "\n")

LOG.write_text("", encoding="utf-8")
for _ in range(90):
    try:
        if requests.get(BASE + "/api/v1/health", timeout=3).ok: break
    except Exception: pass
    time.sleep(2)
log("server up")

# ---------- Figure 5.2: XGBoost vs LSTM, Hyderabad ----------
try:
    import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    from datetime import datetime
    res = {}
    for m in ("xgboost", "lstm"):
        r = requests.get(f"{BASE}/api/v1/predictions/24h", params={"lat": HYD["lat"], "lon": HYD["lon"], "model": m}, timeout=180)
        r.raise_for_status(); res[m] = r.json()
        (OUT / f"forecast_{m}.json").write_text(json.dumps(res[m], indent=1), encoding="utf-8")
    t = [datetime.fromisoformat(p["time_ist"]).strftime("%H:%M") for p in res["xgboost"]["predictions"]]
    fig, ax = plt.subplots(1, 2, figsize=(13, 4.6))
    sty = {"xgboost": ("#1b7f6b", "XGBoost (default)"), "lstm": ("#c2571a", "LSTM")}
    for k, (key, title, unit) in enumerate([("ozone", "Ground-level ozone", "µg/m³"), ("uv", "UV index", "UV index")]):
        for m in ("xgboost", "lstm"):
            P = res[m]["predictions"]; c, lab = sty[m]
            v = [p[key]["value"] for p in P]; lo = [p[key]["lower"] for p in P]; hi = [p[key]["upper"] for p in P]
            ax[k].fill_between(range(len(v)), lo, hi, color=c, alpha=0.12)
            ax[k].plot(range(len(v)), v, color=c, lw=2, marker="o", ms=3, label=lab + " (shaded: 90% range)")
        ax[k].set_title(f"{title}: next 24 hours, Hyderabad"); ax[k].set_ylabel(unit); ax[k].set_xlabel("Time (IST)")
        ax[k].set_xticks(range(0, len(t), 3)); ax[k].set_xticklabels(t[::3]); ax[k].grid(alpha=.25); ax[k].legend(fontsize=8)
    iss = datetime.fromisoformat(res["xgboost"]["issue_time_ist"]).strftime("%d %b %Y, %H:%M IST")
    fig.suptitle(f"XGBoost vs LSTM forecast for Hyderabad (issued {iss})", fontsize=11)
    fig.tight_layout(); fig.savefig(OUT / "xgb_vs_lstm.png", dpi=150); plt.close(fig)
    log("saved xgb_vs_lstm.png")
except Exception:
    log("FORECAST CHART FAILED\n" + traceback.format_exc())

# ---------- Website screenshots ----------
from playwright.sync_api import sync_playwright
HYD_JS = "localStorage.setItem('og_coords', JSON.stringify(%s));" % json.dumps(HYD)

def shot(p, page_url, name, extra_init="", action=None, wait=6000, full=True):
    try:
        b = p.chromium.launch(channel="msedge")
        ctx = b.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1.5, locale="en-IN", timezone_id="Asia/Kolkata")
        ctx.add_init_script(HYD_JS + extra_init + "document.addEventListener('DOMContentLoaded', () => { if (window.Chart) Chart.defaults.animation = false; });")
        pg = ctx.new_page(); pg.goto(BASE + page_url, wait_until="networkidle", timeout=120000)
        if action: action(pg)
        try: pg.wait_for_load_state("networkidle", timeout=120000)
        except Exception: pass
        pg.wait_for_timeout(wait)
        pg.evaluate("""() => { if (window.Chart) { Chart.defaults.animation = false;
            Object.values(Chart.instances || {}).forEach(c => { c.options.animation = false; c.update('none'); }); }
            window.scrollTo(0, 0); }""")
        pg.wait_for_timeout(1500)
        pg.screenshot(path=str(OUT / name), full_page=full)
        b.close(); log("saved", name)
    except Exception:
        log(f"FAILED {name}\n" + traceback.format_exc())

with sync_playwright() as p:
    shot(p, "/index.html", "home_page.png", wait=3000)
    shot(p, "/locations.html", "location_page.png", extra_init="sessionStorage.setItem('og_open_place','1');", wait=9000)
    def pred(pg):
        pg.select_option("#model", "xgboost")
        pg.wait_for_timeout(1500)
        btn = pg.locator("button:has-text('Forecast'), button:has-text('Predict'), #run, #go").first
        try:
            if btn.count(): btn.click()
        except Exception: pass
    shot(p, "/predictions.html", "predictions_page.png", action=pred, wait=9000)
    shot(p, "/analytics.html", "analytics_page.png", action=lambda pg: (pg.wait_for_timeout(4000), pg.select_option("#preset", label="Hyderabad"), pg.wait_for_timeout(4000), pg.click(".range-row button[data-days='30']")), wait=12000)
    shot(p, "/dashboard.html", "dashboard.png", wait=12000)
    shot(p, "/login.html", "login_page.png", wait=2500)
    shot(p, "/signup.html", "signup_page.png", wait=2500)
log("ALL DONE")
