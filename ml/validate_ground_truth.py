"""Ground-truth check: how close is CAMS surface ozone to real station measurements?

The forecast models learn from CAMS (a model), not from sensors. This script measures the
gap between the two, so the project can state how far "matches CAMS" is from "matches the
air outside". It compares hourly station ozone with the CAMS value for the same place and
hour and writes ``docs/ground-truth-validation.md`` plus a JSON file with every number.

Station data can come from either source:

1. CSV files you download yourself (works today, no key)::

       python -m ml.validate_ground_truth csv data/external/stations/*.csv

   Each file is one station. It needs a time column and an ozone column (µg/m³). Station
   coordinates come from ``latitude`` / ``longitude`` columns, or from ``--lat`` / ``--lon``
   when there is one file. Times are taken as Indian Standard Time unless ``--tz UTC``.
   CPCB "CCR" exports (title rows above the header, ``From Date`` / ``To Date`` columns)
   are read as they are.

2. OpenAQ (needs a free key in ``OPENAQ_API_KEY``)::

       python -m ml.validate_ground_truth openaq --start 2026-01-01 --end 2026-03-31

   Looks for ozone stations within ``--radius-km`` of the 38 OzoneGuard locations.

STATUS: the comparison maths and the CSV reader are covered by tests on synthetic data.
The OpenAQ downloader is written from the OpenAQ v3 documentation and has NOT been run
against the live service (no key was available); treat its first run as a trial.
"""
from __future__ import annotations

import argparse
import io
import json
import logging
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from ml import config

log = logging.getLogger("ozoneguard.groundtruth")

AQ_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
OPENAQ_URL = "https://api.openaq.org/v3"
OUT_MD = config.ROOT / "docs" / "ground-truth-validation.md"
OUT_JSON = config.DATA / "validation" / "ground_truth_metrics.json"

STATION_LIMITS = (0.0, 600.0)        # µg/m³; same physical limits as the CAMS QC (ml/config.py)
MIN_HOURS = 100                      # a station needs at least this many matched hours to be reported
PPB_TO_UGM3 = 1.96                   # ozone at 25 °C and 1 atm (CPCB reporting convention)

TIME_NAMES = ["time_utc", "time", "datetime", "timestamp", "from date", "from_date", "date", "date time", "local time"]
OZONE_NAMES = ["ozone", "o3", "ozone (ug/m3)", "ozone (µg/m³)", "ozone(ug/m3)", "o3 (ug/m3)", "o3 (µg/m³)", "value"]
LAT_NAMES, LON_NAMES = ["latitude", "lat"], ["longitude", "lon", "lng", "long"]
NAME_NAMES = ["station", "station name", "station_name", "location", "name"]


# ------------------------------------------------------------------ station input
def _find(columns: list[str], names: list[str]) -> str | None:
    low = {str(c).strip().lower(): c for c in columns}
    return next((low[n] for n in names if n in low), None)


def read_station_csv(path: Path, tz: str = "Asia/Kolkata", lat: float | None = None, lon: float | None = None,
                     unit: str = "ugm3") -> pd.DataFrame:
    """One station file -> columns [station, latitude, longitude, time_utc, station_ozone]."""
    text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    lines = text.splitlines()
    # Skip title rows (CPCB exports start with the station name, parameter list, ...).
    start = next((i for i, ln in enumerate(lines)
                  if _find([c for c in ln.split(",")], TIME_NAMES) and _find([c for c in ln.split(",")], OZONE_NAMES)), None)
    if start is None:
        raise ValueError(f"{path}: no header row with a time column and an ozone column was found.")
    df = pd.read_csv(io.StringIO("\n".join(lines[start:])))
    tcol, ocol = _find(list(df.columns), TIME_NAMES), _find(list(df.columns), OZONE_NAMES)
    t = pd.to_datetime(df[tcol], errors="coerce", dayfirst=True, utc=False)
    if getattr(t.dt, "tz", None) is None:
        t = t.dt.tz_localize(tz, ambiguous="NaT", nonexistent="NaT")
    out = pd.DataFrame({"time_utc": t.dt.tz_convert("UTC").dt.floor("h"),
                        "station_ozone": pd.to_numeric(df[ocol], errors="coerce")})
    if unit == "ppb":
        out["station_ozone"] *= PPB_TO_UGM3
    lat_c, lon_c, name_c = _find(list(df.columns), LAT_NAMES), _find(list(df.columns), LON_NAMES), _find(list(df.columns), NAME_NAMES)
    out["latitude"] = pd.to_numeric(df[lat_c], errors="coerce").iloc[0] if lat_c else lat
    out["longitude"] = pd.to_numeric(df[lon_c], errors="coerce").iloc[0] if lon_c else lon
    if out["latitude"].isna().all() or out["longitude"].isna().all():
        raise ValueError(f"{path}: station coordinates are missing. Add latitude/longitude columns or pass --lat and --lon.")
    out["station"] = str(df[name_c].iloc[0]) if name_c else Path(path).stem
    out = out.dropna(subset=["time_utc"])
    return out.groupby(["station", "latitude", "longitude", "time_utc"], as_index=False)["station_ozone"].mean()


def clean_station(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Remove impossible readings and stuck sensors; report what was removed."""
    n0 = len(df)
    df = df.dropna(subset=["station_ozone"])
    n_missing = n0 - len(df)
    bad = ~df["station_ozone"].between(*STATION_LIMITS)
    df = df[~bad].sort_values("time_utc")
    # A sensor repeating the exact same non-zero value for 12+ hours is treated as stuck.
    run = df["station_ozone"].ne(df["station_ozone"].shift()).cumsum()
    size = df.groupby(run)["station_ozone"].transform("size")
    stuck = (size >= 12) & (df["station_ozone"] > 0)
    return df[~stuck], {"rows": int(n0), "missing": int(n_missing), "out_of_range": int(bad.sum()), "stuck_sensor": int(stuck.sum())}


# ------------------------------------------------------------------ CAMS side
def fetch_cams(lat: float, lon: float, start: str, end: str) -> pd.DataFrame:
    """CAMS surface ozone for one point, hourly, UTC (same request as the training data)."""
    r = requests.get(AQ_URL, params={"latitude": lat, "longitude": lon, "hourly": "ozone", "start_date": start,
                                     "end_date": end, "timezone": "GMT", "domains": "cams_global"}, timeout=120)
    r.raise_for_status()
    payload = r.json()
    if payload.get("error"):
        raise RuntimeError(payload.get("reason"))
    h = payload["hourly"]
    return pd.DataFrame({"time_utc": pd.to_datetime(h["time"], utc=True), "cams_ozone": pd.to_numeric(h["ozone"], errors="coerce")})


# ------------------------------------------------------------------ comparison
def _metrics(d: pd.DataFrame) -> dict:
    e = d["cams_ozone"] - d["station_ozone"]
    ok = d["cams_ozone"].std() > 0 and d["station_ozone"].std() > 0 and len(d) >= 3
    return {"n": int(len(d)), "station_mean": float(d["station_ozone"].mean()), "cams_mean": float(d["cams_ozone"].mean()),
            "bias": float(e.mean()), "mae": float(e.abs().mean()), "rmse": float(math.sqrt((e ** 2).mean())),
            "r": float(d["cams_ozone"].corr(d["station_ozone"])) if ok else None}


def compare(station: pd.DataFrame, cams: pd.DataFrame) -> dict | None:
    """Match on the UTC hour and score CAMS against the station."""
    d = station.merge(cams.dropna(subset=["cams_ozone"]), on="time_utc", how="inner")
    if len(d) < MIN_HOURS:
        return None
    ist_hour = d["time_utc"].dt.tz_convert("Asia/Kolkata").dt.hour
    day = (ist_hour >= 9) & (ist_hour < 17)
    out = {"all": _metrics(d),
           "daytime_09_17_ist": _metrics(d[day]) if day.sum() >= 24 else None,
           "night": _metrics(d[~day]) if (~day).sum() >= 24 else None}
    # Timing check: station hours are averages labelled by their start; if shifting CAMS by an hour
    # correlates better, the two clocks are not aligned and the main numbers are pessimistic.
    lags = {}
    for lag in (-1, 0, 1):
        shifted = cams.assign(time_utc=cams["time_utc"] + pd.Timedelta(hours=lag))
        m = station.merge(shifted.dropna(subset=["cams_ozone"]), on="time_utc", how="inner")
        lags[str(lag)] = float(m["cams_ozone"].corr(m["station_ozone"])) if len(m) >= MIN_HOURS else None
    out["r_by_cams_shift_hours"] = lags
    g = d.assign(h=ist_hour).groupby("h")[["station_ozone", "cams_ozone"]].mean()
    out["average_day_ist"] = [{"hour": int(h), "station": round(float(r.station_ozone), 1), "cams": round(float(r.cams_ozone), 1)} for h, r in g.iterrows()]
    out["period_utc"] = [d["time_utc"].min().isoformat(), d["time_utc"].max().isoformat()]
    return out


def run(stations: pd.DataFrame, cams_fetch=fetch_cams, source: str = "station CSV files") -> dict:
    results, pooled = [], []
    for (name, lat, lon), g in stations.groupby(["station", "latitude", "longitude"]):
        g, qc = clean_station(g)
        if g.empty:
            continue
        start, end = g["time_utc"].min().date().isoformat(), g["time_utc"].max().date().isoformat()
        try:
            cams = cams_fetch(float(lat), float(lon), start, end)
        except Exception as exc:
            log.warning("CAMS fetch failed for %s: %s", name, exc)
            results.append({"station": name, "latitude": float(lat), "longitude": float(lon), "qc": qc, "error": f"CAMS unavailable: {exc}"})
            continue
        res = compare(g, cams)
        if res is None:
            results.append({"station": name, "latitude": float(lat), "longitude": float(lon), "qc": qc,
                            "error": f"fewer than {MIN_HOURS} matched hours"})
            continue
        results.append({"station": name, "latitude": float(lat), "longitude": float(lon), "qc": qc, **res})
        pooled.append(g.merge(cams.dropna(subset=["cams_ozone"]), on="time_utc", how="inner"))
    overall = _metrics(pd.concat(pooled, ignore_index=True)) if pooled else None
    return {"generated_at": datetime.now(timezone.utc).isoformat(), "source": source, "stations": results, "overall": overall,
            "notes": {"cams_grid_km": 45, "units": "µg/m³", "bias": "CAMS minus station (positive = CAMS reads higher)"}}


# ------------------------------------------------------------------ report
def _f(x, n=1):
    return "—" if x is None or (isinstance(x, float) and not np.isfinite(x)) else f"{x:.{n}f}"


def write_report(result: dict, md: Path = OUT_MD, js: Path = OUT_JSON) -> None:
    js.parent.mkdir(parents=True, exist_ok=True)
    js.write_text(json.dumps(result, indent=2, allow_nan=False, default=lambda o: None), encoding="utf-8")
    ok = [s for s in result["stations"] if "all" in s]
    o = result["overall"]
    lines = ["# Ground-truth check: CAMS surface ozone against station measurements", "",
             f"Generated {result['generated_at'][:16].replace('T', ' ')} UTC by `python -m ml.validate_ground_truth`. Station data: {result['source']}.", "",
             "The forecast models are trained on CAMS, which is itself a model. This report compares CAMS with real",
             "station readings for the same place and hour. Bias is CAMS minus station, so a positive bias means CAMS reads higher.", ""]
    if not ok:
        lines += ["**No station had enough matched hours to compare.** See the per-station notes below.", ""]
    else:
        lines += ["## Overall", "",
                  f"* Stations compared: **{len(ok)}**, matched hours: **{o['n']:,}**",
                  f"* Station average **{_f(o['station_mean'])}** µg/m³, CAMS average **{_f(o['cams_mean'])}** µg/m³",
                  f"* Bias **{o['bias']:+.1f}** µg/m³, average error (MAE) **{_f(o['mae'])}** µg/m³, RMSE **{_f(o['rmse'])}** µg/m³, correlation r = **{_f(o['r'], 2)}**", "",
                  "### What this means", "",
                  f"* CAMS reads **{'higher' if o['bias'] > 0 else 'lower'}** than the stations by {abs(o['bias']):.1f} µg/m³ on average.",
                  "* The forecast's tested error (about 10.6 µg/m³) is measured against CAMS. Against real air the total",
                  f"  error cannot be smaller than the CAMS-to-station gap above ({_f(o['mae'])} µg/m³ on average).",
                  "* A station measures one street; a CAMS value covers a square about 45 km wide. Some of the gap is this",
                  "  difference in scale, not an error in either number.", "",
                  "## Per station", "",
                  "| Station | Lat | Lon | Hours | Station avg | CAMS avg | Bias | MAE | RMSE | r | r daytime | r night |",
                  "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for s in ok:
            a, d, n = s["all"], s.get("daytime_09_17_ist") or {}, s.get("night") or {}
            lines.append(f"| {s['station']} | {s['latitude']:.3f} | {s['longitude']:.3f} | {a['n']:,} | {_f(a['station_mean'])} | {_f(a['cams_mean'])} | "
                         f"{a['bias']:+.1f} | {_f(a['mae'])} | {_f(a['rmse'])} | {_f(a['r'], 2)} | {_f(d.get('r'), 2)} | {_f(n.get('r'), 2)} |")
        lines += ["", "### Clock alignment", "",
                  "Correlation when the CAMS series is shifted by −1, 0 and +1 hour. If a shift other than 0 is clearly best,",
                  "the station timestamps and CAMS are not labelled the same way and the numbers above are pessimistic.", "",
                  "| Station | −1 h | 0 h | +1 h |", "|---|---|---|---|"]
        for s in ok:
            lg = s["r_by_cams_shift_hours"]
            lines.append(f"| {s['station']} | {_f(lg['-1'], 2)} | {_f(lg['0'], 2)} | {_f(lg['1'], 2)} |")
    lines += ["", "## Data cleaning per station", "", "| Station | Rows read | Missing | Out of range | Stuck sensor | Note |", "|---|---|---|---|---|---|"]
    for s in result["stations"]:
        q = s["qc"]
        lines.append(f"| {s['station']} | {q['rows']:,} | {q['missing']:,} | {q['out_of_range']:,} | {q['stuck_sensor']:,} | {s.get('error', '')} |")
    lines += ["", "Readings outside 0–600 µg/m³ are dropped, as are runs of 12 or more identical non-zero hours (a stuck sensor).",
              f"A station needs at least {MIN_HOURS} matched hours. Full numbers: `data/validation/ground_truth_metrics.json`.", ""]
    md.write_text("\n".join(lines), encoding="utf-8")


# ------------------------------------------------------------------ OpenAQ (not run against the live service)
def _haversine_km(a_lat, a_lon, b_lat, b_lon) -> float:
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(b_lon - a_lon) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def _openaq(path: str, key: str, params: dict) -> dict:
    for attempt in range(5):
        r = requests.get(f"{OPENAQ_URL}{path}", params=params, headers={"X-API-Key": key}, timeout=60)
        if r.status_code == 429:
            time.sleep(15 * (attempt + 1))
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError("OpenAQ rate limit: gave up after 5 attempts")


def fetch_openaq(start: str, end: str, radius_km: float, key: str, only: list[str] | None = None) -> pd.DataFrame:
    """Hourly ozone from OpenAQ stations near the OzoneGuard locations. UNTESTED against the live API."""
    frames = []
    for lid, name, _region, lat, lon, _role in config.LOCATIONS:
        if only and lid not in only:
            continue
        found = _openaq("/locations", key, {"coordinates": f"{lat},{lon}", "radius": int(min(radius_km, 25) * 1000), "limit": 100})
        for loc in found.get("results", []):
            for sensor in loc.get("sensors", []):
                par = sensor.get("parameter", {})
                if par.get("name") != "o3":
                    continue
                c = loc.get("coordinates", {})
                rows, page = [], 1
                while True:
                    got = _openaq(f"/sensors/{sensor['id']}/hours", key, {"datetime_from": f"{start}T00:00:00Z", "datetime_to": f"{end}T23:59:59Z", "limit": 1000, "page": page})
                    res = got.get("results", [])
                    rows += [{"time_utc": x["period"]["datetimeFrom"]["utc"], "station_ozone": x["value"]} for x in res]
                    if len(res) < 1000:
                        break
                    page += 1
                    time.sleep(1.1)
                if not rows:
                    continue
                df = pd.DataFrame(rows)
                df["time_utc"] = pd.to_datetime(df["time_utc"], utc=True).dt.floor("h")
                units = str(par.get("units", "")).lower()
                if units == "ppm":
                    df["station_ozone"] *= 1000 * PPB_TO_UGM3
                elif units == "ppb":
                    df["station_ozone"] *= PPB_TO_UGM3
                df["station"] = f"{loc.get('name', sensor['id'])} (near {name}, {_haversine_km(lat, lon, c.get('latitude'), c.get('longitude')):.0f} km)"
                df["latitude"], df["longitude"] = c.get("latitude"), c.get("longitude")
                frames.append(df)
                log.info("OpenAQ: %s rows for %s", len(df), df["station"].iloc[0])
                time.sleep(1.1)
    if not frames:
        raise RuntimeError("OpenAQ returned no ozone stations for this search.")
    return pd.concat(frames, ignore_index=True)


# ------------------------------------------------------------------ CLI
def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("csv", help="compare station CSV files you downloaded")
    c.add_argument("files", nargs="+", type=Path)
    c.add_argument("--tz", default="Asia/Kolkata", help="timezone of the times in the files (default: Indian Standard Time)")
    c.add_argument("--lat", type=float)
    c.add_argument("--lon", type=float)
    c.add_argument("--unit", choices=["ugm3", "ppb"], default="ugm3")
    o = sub.add_parser("openaq", help="download station data from OpenAQ (needs OPENAQ_API_KEY)")
    o.add_argument("--start", required=True)
    o.add_argument("--end", required=True)
    o.add_argument("--radius-km", type=float, default=25.0)
    o.add_argument("--only", nargs="*", help="location ids, e.g. delhi hyderabad")
    args = ap.parse_args()

    if args.cmd == "csv":
        if len(args.files) > 1 and (args.lat is not None or args.lon is not None):
            ap.error("--lat/--lon can only be used with a single file; put latitude/longitude columns in each file instead.")
        stations = pd.concat([read_station_csv(f, args.tz, args.lat, args.lon, args.unit) for f in args.files], ignore_index=True)
        source = f"{len(args.files)} CSV file(s)"
    else:
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass
        key = os.getenv("OPENAQ_API_KEY", "").strip()
        if not key:
            ap.error("OPENAQ_API_KEY is not set. Get a free key at https://explore.openaq.org and put it in .env.")
        stations = fetch_openaq(args.start, args.end, args.radius_km, key, args.only)
        source = f"OpenAQ v3, {args.start} to {args.end}, within {args.radius_km:g} km of OzoneGuard locations"
    result = run(stations, source=source)
    write_report(result)
    o_ = result["overall"]
    print(f"Wrote {OUT_MD} and {OUT_JSON}")
    if o_:
        print(f"Overall: n={o_['n']:,}  bias={o_['bias']:+.1f}  MAE={o_['mae']:.1f}  RMSE={o_['rmse']:.1f}  r={o_['r']:.2f}")
    else:
        print("No station had enough matched hours.")


if __name__ == "__main__":
    main()
