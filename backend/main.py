from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.api.routes.analytics import router as analytics_router
from backend.api.routes.health import router as health_router
from backend.api.routes.location import router as location_router
from backend.api.routes.ozone import router as ozone_router
from backend.api.routes.predictions import router as predictions_router
from backend.core.config import settings

app = FastAPI(
    title="OzoneGuard AI API",
    description="Environmental monitoring, history and 24-hour ozone/UV prediction API.",
    version=settings.app_version,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router, prefix="/api/v1")
app.include_router(location_router, prefix="/api/v1")
app.include_router(ozone_router, prefix="/api/v1")
app.include_router(predictions_router, prefix="/api/v1")
app.include_router(analytics_router, prefix="/api/v1")

@app.get("/api")
def api_root():
    return {"service": "OzoneGuard AI API", "docs": "/docs", "version": settings.app_version}


# Serve the website from the same server, so one command runs everything:
#   uvicorn backend.main:app --reload   ->   open http://127.0.0.1:8000
# Mounted last, so every /api/... and /docs route above keeps priority.
FRONTEND_DIR = Path(__file__).resolve().parents[1] / "frontend"
if FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
