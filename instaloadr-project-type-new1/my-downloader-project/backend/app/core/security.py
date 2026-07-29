"""
Rate limiting and shared middleware configuration.

Uses slowapi (a FastAPI-friendly wrapper around limits/Flask-Limiter's
approach) keyed on client IP, so a single caller can't hammer the
extraction endpoint.
"""
import logging

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.middleware.cors import CORSMiddleware

from app.core.config import get_settings

logger = logging.getLogger("uvicorn.error")
settings = get_settings()

# Shared limiter instance - imported by main.py and by individual routes
# via the @limiter.limit(...) decorator.
limiter = Limiter(key_func=get_remote_address, default_limits=[f"{settings.rate_limit_per_minute}/minute"])


def configure_cors(app):
    """Attach CORS middleware restricted to the configured frontend origins."""
    origins = settings.cors_origins_list

    if settings.is_production and not origins:
        # Fail closed and loud rather than silently allowing nothing or,
        # worse, someone "fixing" this later by dropping in allow_origins=["*"].
        logger.warning(
            "CORS_ALLOWED_ORIGINS is empty in production — no browser "
            "origin will be able to call this API. Set it to your "
            "deployed frontend URL(s), e.g. https://yourapp.pages.dev"
        )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
