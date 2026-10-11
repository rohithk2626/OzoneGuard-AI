"""Reverse geocoding for a selected coordinate."""
from typing import Any

import requests

NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
USER_AGENT = "OzoneGuard-AI/0.1 (environmental monitoring project)"


def reverse_geocode(lat: float, lon: float) -> dict[str, Any]:
    params = {
        "lat": lat,
        "lon": lon,
        "format": "jsonv2",
        "zoom": 10,
        "addressdetails": 1,
        "accept-language": "en",
    }
    response = requests.get(
        NOMINATIM_URL,
        params=params,
        headers={"User-Agent": USER_AGENT},
        timeout=10,
    )
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
