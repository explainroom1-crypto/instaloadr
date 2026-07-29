"""Uptime & status monitoring endpoint."""
from datetime import datetime, timezone

from fastapi import APIRouter

from app.core.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check():
    settings = get_settings()
    return {
        "status": "ok",
        "service": settings.app_name,
        "environment": settings.environment.value,
        "mock_mode": settings.mock_mode,
        "time": datetime.now(timezone.utc).isoformat(),
    }
