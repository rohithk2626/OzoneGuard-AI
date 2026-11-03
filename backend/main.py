from pathlib import Path

from fastapi import FastAPI, Request
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

@app.middleware("http")
async def check_for_updates(request: Request, call_next):
    """Website files: tell browsers to check for a newer version on every visit (a quick check
    that returns "not modified" if nothing changed). Without this, browsers may keep showing an
    old copy of a page, its script or its icon for days after the site is updated."""
    response = await call_next(request)
    if not request.url.path.startswith(("/api", "/docs", "/redoc", "/openapi.json")):
        response.headers.setdefault("Cache-Control", "no-cache")
    return response


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
