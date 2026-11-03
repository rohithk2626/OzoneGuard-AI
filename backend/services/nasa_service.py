"""NASA Earthdata OMTO3G total-column ozone retrieval.

The service discovers the newest OMTO3G granule through NASA CMR, downloads it
with an Earthdata bearer token, caches it locally, and extracts the nearest
valid ColumnAmountO3 observation for the requested coordinate.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
import logging
import math
import os
import re
import time

import h5py
import numpy as np
import requests
import earthaccess

from backend.core.config import settings
from backend.core.errors import describe_failure

NASA_DATASET = settings.nasa_short_name
NASA_DATASET_TITLE = "OMI/Aura Ozone (O3) Total Column Daily L2 Global Gridded 0.25 degree"
NASA_DATASET_DOI = "10.5067/Aura/OMI/DATA2425"
NASA_DATASET_URL = "https://data.nasa.gov/dataset/omi-aura-ozone-o3-total-column-daily-l2-global-gridded-0-25-degree-x-0-25-degree-v004-omto-60569"

MAX_FRESH_DAYS = 10             # satellite files normally arrive within a few days; older is labelled "stale"
MAX_DISTANCE_DEGREES = 1.5     # about 165 km; beyond this the "nearest" observation is not this place
FALLBACK_DAYS = 3              # if the newest daily pass misses a point, look up to this many days earlier
KEEP_DAILY_FILES = FALLBACK_DAYS + 1   # newest + the fallback days, about 150 MB each; older files are deleted

log = logging.getLogger("ozoneguard.nasa")
_FILE_DATE = re.compile(r"OMTO3G_(\d{4})m(\d{2})(\d{2})", re.IGNORECASE)   # e.g. ..._OMTO3G_2026m1101_...

_TARGETS = {
    "ozone": ("columnamounto3", "columnamounto3corrected"),
    "lat": ("latitude",),
    "lon": ("longitude",),
    "quality": ("qualityflags", "qualityflag", "quality_flags"),
    "xtrack": ("xtrackqualityflags",),
}

# OMTO3 QualityFlags: the lowest 4 bits hold a quality code. 0 = good sample, 1 = good but sun-glint
# corrected; higher codes are poor or failed retrievals, and 7 means the sample was skipped (its ozone
# value is meaningless, e.g. 88 DU over Hyderabad on 1 Nov 2026). The fill value 65535 gives code 15.
GOOD_QUALITY_CODES = (0, 1)
# XTrackQualityFlags: 0 = this detector row is not affected by the OMI "row anomaly"; anything else
# (including the fill value 255) is a row NASA warns against using.


def _base_metadata(lat: float, lon: float) -> dict[str, Any]:
    return {
        "value": None,
        "unit": "DU",
        "source": "NASA OMI/Aura OMTO3G",
        "dataset": NASA_DATASET,
        "dataset_title": NASA_DATASET_TITLE,
        "doi": NASA_DATASET_DOI,
        "source_url": NASA_DATASET_URL,
        "latitude": lat,
        "longitude": lon,
    }


def _dataset_paths(h5: h5py.File) -> dict[str, str]:
    found: dict[str, str] = {}

    def visitor(name: str, obj: Any) -> None:
        if not isinstance(obj, h5py.Dataset):
            return
        leaf = name.rsplit("/", 1)[-1].lower()
        for kind, names in _TARGETS.items():
            if kind not in found and leaf in names:
                found[kind] = name

    h5.visititems(visitor)
    return found


def _scaled(dataset: h5py.Dataset) -> np.ndarray:
    values = np.asarray(dataset[()])
    fill = dataset.attrs.get("_FillValue")
    scale = dataset.attrs.get("scale_factor", 1.0)
    offset = dataset.attrs.get("add_offset", 0.0)
    values = values.astype(np.float64, copy=False)
    if fill is not None:
        try:
            values[np.isclose(values, float(np.asarray(fill).reshape(-1)[0]), equal_nan=False)] = np.nan
        except Exception:
            pass
    values = values * float(np.asarray(scale).reshape(-1)[0]) + float(np.asarray(offset).reshape(-1)[0])
    return values


_GRANULE_TTL_SECONDS = 3600
_granule_cache: dict[str, Any] = {"at": 0.0, "value": None}


def _latest_granule() -> dict[str, Any]:
    """Newest OMTO3G granule, looked up at most once an hour."""
    now = time.time()
    if _granule_cache["value"] is not None and now - _granule_cache["at"] < _GRANULE_TTL_SECONDS:
        return _granule_cache["value"]
    value = _discover_latest_granule()
    _granule_cache.update(at=now, value=value)
    return value


def _search_newest() -> list[Any]:
    """The most recent granules, newest first.

    CMR returns granules oldest-first by default (the record starts in 2004), so the
    search must ask for the newest ones explicitly. Preferred: sort by start date,
    descending. Fallback for library versions without ``sort_key``: look inside
    recent time windows, widening until something is found.
    """
    base = {"short_name": settings.nasa_short_name, "version": settings.nasa_version}
    try:
        found = earthaccess.search_data(**base, sort_key="-start_date", count=5)
        if found:
            return list(found)
    except (ValueError, TypeError):
        pass
    today = datetime.now(timezone.utc).date()
    for days in (14, 60, 400):
        window = ((today - timedelta(days=days)).isoformat(), (today + timedelta(days=1)).isoformat())
        found = earthaccess.search_data(**base, temporal=window, count=days + 2)
        if found:
            return list(found)
    return []


def _discover_latest_granule() -> dict[str, Any]:
    """Discover the newest OMTO3G granule and prefer its out-of-region HTTPS URL.

    CMR may expose a cloud-hosted granule as an ``s3://`` URL.  A local
    developer machine should not hand that URI to ``requests``.  earthaccess
    resolves the same granule to the DAAC's authenticated HTTPS distribution
    link, which works outside AWS us-west-2 with an Earthdata token.
    """
    # earthaccess uses this environment variable for token-based EDL auth.
    os.environ["EARTHDATA_TOKEN"] = settings.nasa_earthdata_token

    granules = _search_newest()
    if not granules:
        raise RuntimeError("NASA CMR returned no OMTO3G granules.")

    def start_time(granule: Any) -> str:
        try:
            return str(
                granule["umm"]["TemporalExtent"]["RangeDateTime"]["BeginningDateTime"]
            )
        except Exception:
            return ""

    granules = sorted(granules, key=start_time, reverse=True)

    for granule in granules:
        # 'external' means the normal HTTPS distribution link when the caller
        # is outside NASA's in-region AWS environment.
        try:
            urls = granule.data_links(access="external")
        except TypeError:
            # Compatibility with older earthaccess releases.
            urls = granule.data_links(access="out_of_region")

        urls = [
            u for u in urls
            if isinstance(u, str) and u.lower().split("?", 1)[0].endswith((".he5", ".h5", ".hdf"))
        ]
        if not urls:
            continue

        return {
            "id": granule.get("meta", {}).get("native-id") or granule.get("meta", {}).get("concept-id"),
            "time_start": start_time(granule),
            "url": urls[0],
            "granule": granule.get("umm", {}).get("GranuleUR"),
        }

    raise RuntimeError("NASA CMR returned OMTO3G granules but no external HTTPS data URL.")


def _age_days(time_start: str | None) -> int | None:
    """Whole days between the granule's start time and now (UTC)."""
    try:
        t = datetime.fromisoformat(str(time_start).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return max(0, (datetime.now(timezone.utc) - t).days)


def _cache_path(granule: dict[str, Any]) -> Path:
    cache = Path(settings.nasa_cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    name = Path(granule["url"].split("?")[0]).name or "omto3g_latest.he5"
    return cache / name


def _download_granule(granule: dict[str, Any], path: Path) -> None:
    if not settings.nasa_earthdata_token:
        raise RuntimeError("NASA_EARTHDATA_TOKEN is not configured.")
    headers = {"Authorization": f"Bearer {settings.nasa_earthdata_token}"}
    temp = path.with_suffix(path.suffix + ".part")
    with requests.get(granule["url"], headers=headers, stream=True, timeout=(30, 180)) as response:
        if response.status_code in (401, 403):
            raise RuntimeError(
                f"NASA rejected the Earthdata token (HTTP {response.status_code}). Generate a new token, and approve "
                "the 'NASA GESDISC DATA ARCHIVE' application for your Earthdata account (docs/blockers.md).")
        response.raise_for_status()
        with temp.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)
    if not h5py.is_hdf5(temp):
        temp.unlink(missing_ok=True)
        raise RuntimeError(
            "NASA returned a web page instead of the data file. This usually means the Earthdata token has expired "
            "or the 'NASA GESDISC DATA ARCHIVE' application is not approved for the account (docs/blockers.md).")
    temp.replace(path)


def _get_cached_granule() -> tuple[Path, dict[str, Any]]:
    granule = _latest_granule()
    path = _cache_path(granule)
    max_age = timedelta(hours=settings.nasa_cache_max_age_hours)
    stale = path.exists() and datetime.now(timezone.utc) - datetime.fromtimestamp(path.stat().st_mtime, timezone.utc) > max_age
    if not path.exists() or stale or not h5py.is_hdf5(path):
        _download_granule(granule, path)
    _prune_cache(keep=path)
    return path, granule


# ------------------------------------------------------------------ cached daily files
def _file_date(path: Path) -> datetime | None:
    """Observation date of a daily OMTO3G file, read from its name (…_OMTO3G_2026m1101_…)."""
    m = _FILE_DATE.search(path.name)
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=timezone.utc)
    except ValueError:
        return None


def _cached_files() -> list[Path]:
    """Daily OMTO3G files in the cache folder, newest observation date first."""
    cache = Path(settings.nasa_cache_dir)
    if not cache.is_dir():
        return []
    dated = [(d, p) for p in cache.glob("*.he5") if (d := _file_date(p)) is not None]
    return [p for _, p in sorted(dated, key=lambda dp: dp[0], reverse=True)]


def _prune_cache(keep: Path) -> None:
    """Keep the newest KEEP_DAILY_FILES daily files (and always `keep`); delete older ones and leftovers
    of interrupted downloads. Only OMTO3G files in the NASA cache folder are ever touched."""
    for old in _cached_files()[KEEP_DAILY_FILES:]:
        if old.resolve() == keep.resolve():
            continue
        try:
            old.unlink()
            _points_cache.pop(str(old), None)
            log.info("deleted old NASA file %s", old.name)
        except OSError as exc:                      # e.g. the file is open elsewhere: try again next time
            log.warning("could not delete old NASA file %s: %s", old.name, exc)
    cutoff = time.time() - 24 * 3600
    for part in Path(settings.nasa_cache_dir).glob("*.he5.part"):
        try:
            if part.stat().st_mtime < cutoff:
                part.unlink()
        except OSError:
            pass


def _earlier_files(newest: Path) -> list[Path]:
    """Cached daily files from up to FALLBACK_DAYS before `newest`, most recent first."""
    top = _file_date(newest)
    if top is None:
        return []
    return [p for p in _cached_files()
            if (d := _file_date(p)) is not None and timedelta(0) < top - d <= timedelta(days=FALLBACK_DAYS)]


# Observations kept in memory: India plus a margin. The global file holds ~15 million
# candidate scenes; this keeps a few tens of thousands and makes later requests instant.
# One entry per daily file (newest plus the fallback days), keyed by file path.
_REGION = (-2.0, 45.0, 58.0, 107.0)          # lat_min, lat_max, lon_min, lon_max
_points_cache: dict[str, tuple[Any, Any]] = {}


def _region_points(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Valid (ozone, lat, lon) observations near India from one granule, cached per file version."""
    version = path.stat().st_mtime_ns
    hit = _points_cache.get(str(path))
    if hit and hit[0] == version:
        return hit[1]
    with h5py.File(path, "r") as h5:
        paths = _dataset_paths(h5)
        missing = [k for k in ("ozone", "lat", "lon") if k not in paths]
        if missing:
            raise RuntimeError(f"OMTO3G file is missing required datasets: {', '.join(missing)}")
        ozone = _scaled(h5[paths["ozone"]]).reshape(-1)
        lats = _scaled(h5[paths["lat"]]).reshape(-1)
        lons = _scaled(h5[paths["lon"]]).reshape(-1)
        quality = h5[paths["quality"]][...].reshape(-1) if "quality" in paths else None
        xtrack = h5[paths["xtrack"]][...].reshape(-1) if "xtrack" in paths else None
    if not (ozone.shape == lats.shape == lons.shape):
        raise RuntimeError("OMTO3G ozone, latitude and longitude arrays have different sizes.")

    # Keep only observations NASA marks as good: a good quality code, a row free of the row anomaly,
    # and a value inside a physically plausible total-column range.
    valid = np.isfinite(ozone) & np.isfinite(lats) & np.isfinite(lons)
    valid &= (ozone > 50) & (ozone < 700)
    if quality is not None and quality.shape == ozone.shape:
        valid &= np.isin(quality.astype(np.int64) & 0b1111, GOOD_QUALITY_CODES)
    if xtrack is not None and xtrack.shape == ozone.shape:
        valid &= xtrack.astype(np.int64) == 0
    lat_min, lat_max, lon_min, lon_max = _REGION
    valid &= (lats >= lat_min) & (lats <= lat_max) & (lons >= lon_min) & (lons <= lon_max)
    if not np.any(valid):
        raise RuntimeError("No valid ozone observations were found over India in the OMTO3G granule.")
    value = (ozone[valid].astype(np.float32), lats[valid].astype(np.float32), lons[valid].astype(np.float32))
    if len(_points_cache) >= KEEP_DAILY_FILES + 1:             # newest + fallback days; drop the oldest entry
        _points_cache.pop(next(iter(_points_cache)))
    _points_cache[str(path)] = (version, value)
    return value


def _nearest_ozone(path: Path, lat: float, lon: float) -> tuple[float, float, str | None]:
    ozone, lats, lons = _region_points(path)
    # Longitude wrap-safe distance.
    dlon = np.abs(((lons - lon + 180.0) % 360.0) - 180.0)
    dlat = lats - lat
    # Latitude-aware local distance approximation.
    score = dlat * dlat + (dlon * math.cos(math.radians(lat))) ** 2
    idx = int(np.argmin(score))
    distance_deg = float(math.sqrt(score[idx]))
    return float(ozone[idx]), distance_deg, f"{float(lats[idx]):.4f},{float(lons[idx]):.4f}"


def get_current_ozone(lat: float, lon: float) -> dict[str, Any]:
    result = _base_metadata(lat, lon)
    if not settings.nasa_earthdata_token:
        result.update({
            "status": "requires_earthdata_auth",
            "message": "Configure NASA_EARTHDATA_TOKEN in .env. No ozone value is fabricated.",
        })
        return result

    try:
        path, granule = _get_cached_granule()
        value, distance_deg, source_cell = _nearest_ozone(path, lat, lon)
        observed, granule_id, earlier_pass = granule.get("time_start"), granule.get("granule"), False
        if distance_deg > MAX_DISTANCE_DEGREES:
            # The satellite covers India in strips; a point missed today is usually covered a day earlier.
            for older in _earlier_files(path):
                try:
                    v, d, c = _nearest_ozone(older, lat, lon)
                except Exception as exc:             # an unreadable old file: skip it
                    log.warning("could not read %s: %s", older.name, exc)
                    continue
                if d <= MAX_DISTANCE_DEGREES:
                    value, distance_deg, source_cell = v, d, c
                    observed = _file_date(older).strftime("%Y-%m-%dT00:00:00.000Z")
                    granule_id, earlier_pass = older.name, True
                    break
        if distance_deg > MAX_DISTANCE_DEGREES:
            result.update({
                "status": "unavailable",
                "message": f"The recent satellite passes have no valid ozone observation within {MAX_DISTANCE_DEGREES}° "
                           f"of this point (nearest is {distance_deg:.1f}° away). No value is shown.",
                "observation_time": granule.get("time_start"),
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
            })
            return result
        age_days = _age_days(observed)
        recent = age_days is not None and age_days <= MAX_FRESH_DAYS
        if not recent:
            message = (f"The newest available NASA OMTO3G file is {age_days if age_days is not None else 'an unknown number of'} "
                       "days old, so this is not a current reading.")
        elif earlier_pass:
            message = ("The newest satellite pass did not cover this point, so this is the nearest valid OMTO3G "
                       "observation from the pass shown, a day or two earlier.")
        else:
            message = "Nearest valid OMTO3G observation from the newest available daily file."
        result.update({
            "value": round(value, 2),
            "status": "live" if recent else "stale",
            "message": message,
            "observation_time": observed,
            "observation_age_days": age_days,
            "from_earlier_pass": earlier_pass,
            "granule": granule_id,
            "source_cell": source_cell,
            "distance_degrees": round(distance_deg, 4),
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
        })
        return result
    except Exception as exc:
        result.update({
            "status": "unavailable",
            "message": describe_failure(exc),
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
        })
        return result
