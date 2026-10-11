from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query

from backend.schemas.location import LocationOverview, LocationValidation
from backend.services.geocoding_service import reverse_geocode
from backend.services.geospatial_service import is_within_india_bounds
from backend.services.nasa_service import get_current_ozone
from backend.services.weather_service import get_current_weather_uv
from ml.config import LOCATIONS
from ml.risk import uv_risk_label

router = APIRouter(prefix="/location", tags=["Location"])


def _uv_risk(uv: float | None) -> dict[str, str | None]:
    """WHO category on the rounded index -- the same rule the Predictions page uses (ml/risk.py)."""
    label = uv_risk_label(uv)
    if label == "Unavailable":
        return {"level": "Unavailable", "color_class": "unknown"}
    return {"level": label, "color_class": label.lower().replace(" ", "-")}


@router.get("/presets")
def presets():
    """The 38 named points the models were trained and tested on, for quick selection."""
    return [{"id": lid, "name": name, "region": region, "latitude": lat, "longitude": lon}
            for lid, name, region, lat, lon, _role in LOCATIONS]


@router.get("/validate", response_model=LocationValidation)
def validate_location(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
):
    valid = is_within_india_bounds(lat, lon)
    message = (
        "Coordinate is inside India."
        if valid
        else "Coordinate is outside India (in the sea or in another country)."
    )
    return LocationValidation(valid=valid, latitude=lat, longitude=lon, message=message)


@router.get("/overview", response_model=LocationOverview)
def location_overview(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
):
    if not is_within_india_bounds(lat, lon):
        raise HTTPException(status_code=400, detail="Selected point is outside India.")

    errors: list[str] = []
    try:
        weather = get_current_weather_uv(lat, lon)
    except Exception as exc:
        weather = {"source": "Open-Meteo", "status": "unavailable", "message": str(exc)}
        errors.append("Weather/UV provider unavailable")

    try:
        place = reverse_geocode(lat, lon)
    except Exception as exc:
        place = {"source": "OpenStreetMap Nominatim", "status": "unavailable", "message": str(exc)}
        errors.append("Reverse geocoding unavailable")

    ozone = get_current_ozone(lat, lon)
    uv = weather.get("uv_index")

    return {
        "location": {
            "latitude": lat,
            "longitude": lon,
            "place": place,
        },
        "weather": weather,
        "ozone": ozone,
        "risk": _uv_risk(uv),
        "data_sources": [
            {"name": "Open-Meteo", "purpose": "Current weather and UV", "status": "live" if weather.get("status") != "unavailable" else "unavailable"},
            {"name": "NASA OMI/Aura OMTO3G", "purpose": "Satellite total-column ozone", "status": ozone.get("status", "unknown")},
            {"name": "OpenStreetMap Nominatim", "purpose": "Coordinate reverse geocoding", "status": "live" if place.get("status") != "unavailable" else "unavailable"},
        ],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "warnings": errors,
    }
