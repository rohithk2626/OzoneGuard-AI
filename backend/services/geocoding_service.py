"""Reverse geocoding (coordinate -> place name) with OpenStreetMap Nominatim.

Nominatim is a free public service with a usage policy: an identifying User-Agent, at most one
request per second, and results cached rather than requested again. Place names do not change, so
answers are kept for 30 days, keyed by the coordinate rounded to 3 decimals (about 100 m; names are
looked up at city level anyway). Requests are spaced at least 1 second apart. Failures are not cached.
"""
import threading
import time
from typing import Any

import requests

NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
USER_AGENT = "OzoneGuard-AI/1.0 (student environmental monitoring project; github.com/rohithk2626/OzoneGuard-AI)"

CACHE_TTL_S = 30 * 24 * 3600
CACHE_MAX = 5000
MIN_INTERVAL_S = 1.0

_cache: dict[tuple[float, float], tuple[float, dict[str, Any]]] = {}
_cache_lock = threading.Lock()
_request_lock = threading.Lock()   # one request at a time, spaced MIN_INTERVAL_S apart
_last_request = 0.0


def _key(lat: float, lon: float) -> tuple[float, float]:
    return round(float(lat), 3), round(float(lon), 3)


def _cached(key: tuple[float, float]) -> dict[str, Any] | None:
    with _cache_lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < CACHE_TTL_S:
            return dict(hit[1])
    return None


def _store(key: tuple[float, float], place: dict[str, Any]) -> None:
    with _cache_lock:
        if len(_cache) >= CACHE_MAX:
            _cache.pop(min(_cache, key=lambda k: _cache[k][0]))
        _cache[key] = (time.time(), place)


def _fetch(lat: float, lon: float) -> dict[str, Any]:
    global _last_request
    params = {
        "lat": lat,
        "lon": lon,
        "format": "jsonv2",
        "zoom": 10,
        "addressdetails": 1,
        "accept-language": "en",
    }
    with _request_lock:
        wait = MIN_INTERVAL_S - (time.monotonic() - _last_request)
        if wait > 0:
            time.sleep(wait)
        try:
            response = requests.get(NOMINATIM_URL, params=params, headers={"User-Agent": USER_AGENT}, timeout=10)
        finally:
            _last_request = time.monotonic()
    response.raise_for_status()
    payload = response.json()
    address = payload.get("address", {})
    return {
        "display_name": payload.get("display_name"),
        "city": address.get("city") or address.get("town") or address.get("village") or address.get("municipality"),
        "district": address.get("state_district") or address.get("county"),
        "state": address.get("state"),
        "country": address.get("country"),
        "country_code": address.get("country_code"),
        "source": "OpenStreetMap Nominatim",
    }


def reverse_geocode(lat: float, lon: float) -> dict[str, Any]:
    key = _key(lat, lon)
    hit = _cached(key)
    if hit is not None:
        return hit
    place = _fetch(*key)
    _store(key, place)
    return dict(place)
