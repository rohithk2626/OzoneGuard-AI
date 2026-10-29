import math

from fastapi import APIRouter, HTTPException, Query

from backend.schemas.predictions import PredictionResponse
from backend.services.geospatial_service import is_within_india_bounds
from backend.services.prediction_service import MODEL_NAMES, PredictionUnavailable, load_artifacts, predict_24h, resolve_model

router = APIRouter(prefix="/predictions", tags=["Predictions"])

MODEL_QUERY = Query(None, pattern="^(xgboost|lstm)$",
                    description="Model family: 'xgboost' (default) or 'lstm'. Default can be changed with env OZONEGUARD_MODEL.")


@router.get("/24h", response_model=PredictionResponse)
def predictions_24h(
    lat: float = Query(..., ge=-90, le=90, description="Latitude (decimal degrees)"),
    lon: float = Query(..., ge=-180, le=180, description="Longitude (decimal degrees)"),
    model: str | None = MODEL_QUERY,
):
    """Hourly surface-ozone and UV-index forecast for the next 24 hours with
    90 % conformal ranges, WHO UV risk, peak UV and high-risk windows."""
    if not is_within_india_bounds(lat, lon):
        raise HTTPException(status_code=400, detail="Selected point is outside India.")
    try:
        return predict_24h(lat, lon, model=model)
    except PredictionUnavailable as exc:
        raise HTTPException(status_code=503, detail={"status": exc.status, "message": str(exc)})


@router.get("/model-info")
def model_info(model: str | None = MODEL_QUERY):
    """Model metadata and headline evaluation metrics (from models/<model>/metrics.json)."""
    try:
        art = load_artifacts(model)
    except PredictionUnavailable as exc:
        raise HTTPException(status_code=503, detail={"status": exc.status, "message": str(exc)})
    m = art["metrics"]
    return _json_safe({"model": art["name"], "metadata": art["meta"], "test": {t: m["test"][t]["model"] for t in ("ozone", "uv")},
                       "spatial_holdout_test": {t: m["spatial_holdout_test"][t]["model"] for t in ("ozone", "uv")},
                       "baselines_test": {t: m["test"][t]["baselines"] for t in ("ozone", "uv")}})


@router.get("/models")
def available_models():
    """Both model families side by side: which are trained, which one is the default, and their test metrics
    (same test period, same locations, same rows), so the frontend or a person can compare them."""
    out = {"default": resolve_model(None), "models": {}}
    for name in MODEL_NAMES:
        try:
            art = load_artifacts(name)
        except PredictionUnavailable as exc:
            out["models"][name] = {"available": False, "reason": str(exc)}
            continue
        m = art["metrics"]
        out["models"][name] = {
            "available": True,
            "algorithm": art["meta"]["models"]["ozone"]["algorithm"],
            "trained_at": art["meta"].get("trained_at"),
            "test": {t: m["test"][t]["model"] for t in ("ozone", "uv")},
            "spatial_holdout_test": {t: m["spatial_holdout_test"][t]["model"] for t in ("ozone", "uv")},
            "interval_90_test": {t: m["test"][t]["interval_90"] for t in ("ozone", "uv")},
        }
    return _json_safe(out)


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
