"""FastAPI application entrypoint."""

from fastapi import FastAPI

from app.api.routes.health import router as health_router
from app.api.routes.requirements import router as requirements_router
from app.config import get_settings
from app.logging import configure_logging
from app.logging import get_logger


settings = get_settings()
configure_logging(settings.log_level)
logger = get_logger(__name__)

app = FastAPI(title=settings.app_name)
app.include_router(health_router)
app.include_router(requirements_router)


@app.on_event("startup")
async def startup_event() -> None:
    """Log application startup configuration."""
    logger.info(
        "Starting application env=%s model=%s api_key_configured=%s",
        settings.app_env,
        settings.llm_model,
        bool(settings.api_key),
    )
