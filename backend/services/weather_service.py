"""Open-Meteo weather and UV integration."""
from datetime import datetime, timezone
from typing import Any

import requests

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"


def _pick(values: list[Any] | None, index: int = 0):
    if not values or index >= len(values):
        return None
    return values[index]


def get_current_weather_uv(lat: float, lon: float) -> dict[str, Any]:
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": ",".join([
            "temperature_2m",
            "relative_humidity_2m",
            "apparent_temperature",
            "is_day",
            "precipitation",
            "rain",
            "cloud_cover",
            "surface_pressure",
            "wind_speed_10m",
            "wind_direction_10m",
            "weather_code",
            "uv_index",
            "uv_index_clear_sky",
        ]),
        "timezone": "auto",
        "forecast_days": 1,
    }
    response = requests.get(OPEN_METEO_URL, params=params, timeout=15)
    response.raise_for_status()
    payload = response.json()
    current = payload.get("current", {})
    units = payload.get("current_units", {})

    return {
        "time": current.get("time"),
        "timezone": payload.get("timezone"),
        "temperature": current.get("temperature_2m"),
        "temperature_unit": units.get("temperature_2m", "°C"),
        "feels_like": current.get("apparent_temperature"),
        "humidity": current.get("relative_humidity_2m"),
        "humidity_unit": units.get("relative_humidity_2m", "%"),
        "cloud_cover": current.get("cloud_cover"),
        "pressure": current.get("surface_pressure"),
        "wind_speed": current.get("wind_speed_10m"),
        "wind_direction": current.get("wind_direction_10m"),
        "precipitation": current.get("precipitation"),
        "rain": current.get("rain"),
        "weather_code": current.get("weather_code"),
        "is_day": bool(current.get("is_day", 0)),
        "uv_index": current.get("uv_index"),
        "uv_index_clear_sky": current.get("uv_index_clear_sky"),
        "source": "Open-Meteo",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
    }
