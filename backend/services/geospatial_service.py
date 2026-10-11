"""Geospatial helpers for the location workflow.

A coordinate is accepted when it falls inside India's outline, not just inside a
latitude/longitude rectangle, so clicks in the sea or in neighbouring countries are
rejected.

Outline: ``backend/data/india_boundary.json`` -- DataMeet ``india-composite`` (CC0),
which follows the official Survey of India boundary, simplified and buffered outward
by about 0.2 degrees (~20 km). The buffer keeps coastal and border towns valid and
matches the coarse (~45 km) grid of the data sources. The islands (Andaman & Nicobar,
Lakshadweep) are separate rings in the same file.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

BOUNDARY_FILE = Path(__file__).resolve().parents[1] / "data" / "india_boundary.json"

# Broad rectangle: a cheap first test, and the fallback if the outline file is missing.
INDIA_LAT_MIN = 6.0
INDIA_LAT_MAX = 37.5
INDIA_LON_MIN = 68.0
INDIA_LON_MAX = 97.6


@lru_cache(maxsize=1)
def _rings() -> tuple[tuple[tuple[float, float, float, float], tuple[tuple[float, float], ...]], ...]:
    """Outline rings as ((min_lon, min_lat, max_lon, max_lat), ((lon, lat), ...))."""
    if not BOUNDARY_FILE.exists():
        return ()
    doc = json.loads(BOUNDARY_FILE.read_text(encoding="utf-8"))
    out = []
    for ring in doc["rings"]:
        pts = tuple((float(x), float(y)) for x, y in ring)
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        out.append(((min(xs), min(ys), max(xs), max(ys)), pts))
    return tuple(out)


def _in_ring(lon: float, lat: float, pts: tuple[tuple[float, float], ...]) -> bool:
    """Ray-casting point-in-polygon test (even-odd rule)."""
    inside = False
    j = len(pts) - 1
    for i in range(len(pts)):
        xi, yi = pts[i]
        xj, yj = pts[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def boundary_available() -> bool:
    return bool(_rings())


def is_within_india_bounds(latitude: float, longitude: float) -> bool:
    """True when the coordinate lies inside India's (slightly buffered) outline."""
    if not (INDIA_LAT_MIN <= latitude <= INDIA_LAT_MAX and INDIA_LON_MIN <= longitude <= INDIA_LON_MAX):
        return False
    rings = _rings()
    if not rings:  # outline file missing: keep the old rectangle behaviour rather than fail
        return True
    for (x0, y0, x1, y1), pts in rings:
        if x0 <= longitude <= x1 and y0 <= latitude <= y1 and _in_ring(longitude, latitude, pts):
            return True
    return False
