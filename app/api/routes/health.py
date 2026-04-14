"""Health check routes."""

from fastapi import APIRouter

from app.config import get_settings
from app.schemas.responses import HealthResponse


router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def healthcheck() -> HealthResponse:
    """Application-wide health check."""
    settings = get_settings()
    return HealthResponse(
        status="ok",
        app=settings.app_name,
        environment=settings.app_env,
    )
