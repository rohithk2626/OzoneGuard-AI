from fastapi import APIRouter

from backend.core.config import settings

router = APIRouter(tags=["Health"])


@router.get("/health")
def health():
    return {
        "status": "healthy",
        "service": "OzoneGuard AI",
        "version": settings.app_version,
    }
