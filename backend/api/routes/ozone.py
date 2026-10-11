from fastapi import APIRouter, Query

from backend.services.nasa_service import get_current_ozone

router = APIRouter(prefix="/ozone", tags=["Ozone"] )


@router.get("/current")
def current_ozone(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
):
    return get_current_ozone(lat, lon)
