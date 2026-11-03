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
log("ALL DONE")
