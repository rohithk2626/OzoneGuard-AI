from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, Query

from backend.services.analytics_service import (
    EARLIEST, MAX_DAYS, AnalyticsUnavailable, InvalidRange, get_history, today_ist,
)
from backend.services.geospatial_service import is_within_india_bounds

router = APIRouter(prefix="/analytics", tags=["Analytics"])


@router.get("/history")
def history(
    lat: float = Query(..., ge=-90, le=90, description="Latitude (decimal degrees)"),
    lon: float = Query(..., ge=-180, le=180, description="Longitude (decimal degrees)"),
    start: date | None = Query(None, description="First day, YYYY-MM-DD (IST). Default: 29 days before `end`."),
    end: date | None = Query(None, description="Last day, YYYY-MM-DD (IST). Default: today."),
):
    """Real daily history of ground-level ozone, UV index and weather for any point in India.

    Days are Indian days (IST). The range may be at most 366 days and cannot start before
    4 August 2022, when the CAMS record for India begins."""
    if not is_within_india_bounds(lat, lon):
        raise HTTPException(status_code=400, detail="Selected point is outside India.")
    end = end or today_ist()
    start = start or end - timedelta(days=29)
    try:
        return get_history(lat, lon, start, end)
    except InvalidRange as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except AnalyticsUnavailable as exc:
        raise HTTPException(status_code=503, detail={"status": exc.status, "message": str(exc)})


@router.get("/limits")
def limits():
    """Earliest available day, today's date in IST and the longest allowed range."""
    return {"earliest": EARLIEST.isoformat(), "latest": today_ist().isoformat(), "max_days": MAX_DAYS}
