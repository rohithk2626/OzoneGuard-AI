"""Historical data collection for OzoneGuard AI.

Two entry points produce the SAME raw schema (one Parquet file per location
under data/raw/openmeteo/):

1. ``python -m ml.collect_data fetch``  -- downloads directly from the
   Open-Meteo APIs (CAMS air quality + archived NWP forecasts). Chunked by
   year, cached per chunk, resumable, with retry/back-off for HTTP 429.

2. ``python -m ml.collect_data import-export <file.csv.gz>`` -- imports the
   browser-side export used to build dataset v1 (the build sandbox had no
   direct network route to Open-Meteo, so the identical API calls were made
   from a browser and saved as one gzip CSV). Same URLs, same variables.

Sources
-------
* CAMS global atmospheric composition forecasts (ECMWF/Copernicus), via the
  Open-Meteo Air Quality API, domain ``cams_global`` (~0.4°, 3-hourly native,
  served hourly). Licence: CC BY 4.0 -- credit CAMS and Open-Meteo.
* Archived NWP forecasts via the Open-Meteo Historical Forecast API
  (``best_match`` model selection). Licence CC BY 4.0.
"""
from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path

import pandas as pd
import requests

from ml import config

log = logging.getLogger("ozoneguard.collect")

AQ_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
HF_URL = "https://historical-forecast-api.open-meteo.com/v1/forecast"

META_COLS = ["location_id", "name", "region", "role", "req_lat", "req_lon",
             "aq_lat", "aq_lon", "aq_elev", "wx_lat", "wx_lon", "wx_elev", "time_utc"]
VALUE_COLS = [f"cams_{v}" for v in config.CAMS_VARS] + [f"wx_{v}" for v in config.WX_VARS]
RAW_COLUMNS = META_COLS + VALUE_COLS


def _year_chunks(start: str, end: str) -> list[tuple[str, str]]:
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    out, cur = [], s
    while cur <= e:
        nxt = min(cur + pd.DateOffset(years=1) - pd.Timedelta(days=1), e)
        out.append((cur.date().isoformat(), nxt.date().isoformat()))
        cur = nxt + pd.Timedelta(days=1)
    return out


def _get(url: str, params: dict, retries: int = 8) -> dict:
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, timeout=120)
            if r.status_code == 429 or r.status_code >= 500:
                wait = 65 if r.status_code == 429 else 15
                log.warning("HTTP %s, sleeping %ss", r.status_code, wait)
                time.sleep(wait)
                continue
            payload = r.json()
            if payload.get("error"):
                raise RuntimeError(payload.get("reason"))
            return payload
        except requests.RequestException as exc:  # network hiccup
            log.warning("request failed (%s) attempt %s", exc, attempt + 1)
            time.sleep(10 * (attempt + 1))
    raise RuntimeError(f"giving up on {url}")


def fetch_location(loc: tuple, start: str, end: str, cache_dir: Path) -> pd.DataFrame:
    lid, name, region, lat, lon, role = loc
    frames = []
    for s, e in _year_chunks(start, end):
        chunk_file = cache_dir / "chunks" / f"{lid}_{s}_{e}.json"
        chunk_file.parent.mkdir(parents=True, exist_ok=True)
        if chunk_file.exists():
            aq, wx = json.loads(chunk_file.read_text())
        else:
            aq = _get(AQ_URL, {"latitude": lat, "longitude": lon, "hourly": ",".join(config.CAMS_VARS),
                               "start_date": s, "end_date": e, "timezone": "GMT", "domains": "cams_global"})
            wx = _get(HF_URL, {"latitude": lat, "longitude": lon, "hourly": ",".join(config.WX_VARS),
                               "start_date": s, "end_date": e, "timezone": "GMT"})
            chunk_file.write_text(json.dumps([aq, wx]))
            time.sleep(1.5)
        a = pd.DataFrame(aq["hourly"]).rename(columns={v: f"cams_{v}" for v in config.CAMS_VARS})
        w = pd.DataFrame(wx["hourly"]).rename(columns={v: f"wx_{v}" for v in config.WX_VARS})
        df = a.merge(w, on="time", how="outer")
        df["aq_lat"], df["aq_lon"], df["aq_elev"] = aq["latitude"], aq["longitude"], aq.get("elevation")
        df["wx_lat"], df["wx_lon"], df["wx_elev"] = wx["latitude"], wx["longitude"], wx.get("elevation")
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)
    df["time_utc"] = pd.to_datetime(df.pop("time"), utc=True)
    df["location_id"], df["name"], df["region"], df["role"] = lid, name, region, role
    df["req_lat"], df["req_lon"] = lat, lon
    return df[RAW_COLUMNS]


def save_raw(df: pd.DataFrame, out_dir: Path = config.RAW_OPENMETEO) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for lid, g in df.groupby("location_id"):
        p = out_dir / f"{lid}.parquet"
        g.sort_values("time_utc").to_parquet(p, index=False)
        paths.append(p)
    return paths


def import_export(path: Path) -> pd.DataFrame:
    """Read the browser export (headerless CSV, RAW_COLUMNS order)."""
    df = pd.read_csv(path, header=None, names=RAW_COLUMNS, compression="infer")
    df["time_utc"] = pd.to_datetime(df["time_utc"], utc=True)
    return df


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("--start", default=config.START_DATE)
    f.add_argument("--end", default=config.END_DATE)
    f.add_argument("--only", nargs="*", help="location ids (phase-1 dev subset)")
    i = sub.add_parser("import-export")
    i.add_argument("path", type=Path)
    args = ap.parse_args()

    if args.cmd == "fetch":
        locs = [l for l in config.LOCATIONS if not args.only or l[0] in args.only]
        for loc in locs:
            out = config.RAW_OPENMETEO / f"{loc[0]}.parquet"
            if out.exists():
                log.info("skip %s (exists)", loc[0])
                continue
            log.info("fetching %s", loc[0])
            save_raw(fetch_location(loc, args.start, args.end, config.RAW_OPENMETEO))
    else:
        df = import_export(args.path)
        paths = save_raw(df)
        log.info("imported %s rows into %s files", len(df), len(paths))


if __name__ == "__main__":
    main()
