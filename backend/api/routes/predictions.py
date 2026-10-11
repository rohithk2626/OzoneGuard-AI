import math

from fastapi import APIRouter, HTTPException, Query

from backend.schemas.predictions import PredictionResponse
from backend.services.geospatial_service import is_within_india_bounds
from backend.services.prediction_service import PredictionUnavailable, load_artifacts, predict_24h

router = APIRouter(prefix="/predictions", tags=["Predictions"])


@router.get("/24h", response_model=PredictionResponse)
def predictions_24h(
    lat: float = Query(..., ge=-90, le=90, description="Latitude (decimal degrees)"),
    lon: float = Query(..., ge=-180, le=180, description="Longitude (decimal degrees)"),
):
    """Hourly surface-ozone and UV-index forecast for the next 24 hours with
    90 % conformal ranges, WHO UV risk, peak UV and high-risk windows."""
    if not is_within_india_bounds(lat, lon):
        raise HTTPException(status_code=400, detail="Selected point is outside India.")
    try:
        return predict_24h(lat, lon)
    except PredictionUnavailable as exc:
        raise HTTPException(status_code=503, detail={"status": exc.status, "message": str(exc)})


@router.get("/model-info")
def model_info():
    """Model metadata and headline evaluation metrics (from models/metrics.json)."""
    try:
        art = load_artifacts()
    except PredictionUnavailable as exc:
        raise HTTPException(status_code=503, detail={"status": exc.status, "message": str(exc)})
    m = art["metrics"]
    return _json_safe({"metadata": art["meta"], "test": {t: m["test"][t]["model"] for t in ("ozone", "uv")},
                       "spatial_holdout_test": {t: m["spatial_holdout_test"][t]["model"] for t in ("ozone", "uv")},
                       "baselines_test": {t: m["test"][t]["baselines"] for t in ("ozone", "uv")}})


def _json_safe(value):
    """Replace NaN / ±Infinity with None so the response is valid JSON.

    model_metadata.json stores XGBoost's default `missing: NaN`. Python reads that
    back as float('nan'), which strict JSON (and FastAPI's response encoder) rejects.
    """
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value
