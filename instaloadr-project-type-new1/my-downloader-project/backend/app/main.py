"""
Main FastAPI application entry point.

Run locally with:
    uvicorn app.main:app --reload --port 8000
"""
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.routes import bundle, fetch, health, streaming
from app.core.config import get_settings
from app.core.security import configure_cors, limiter

logger = logging.getLogger("uvicorn.error")
settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    description="Backend API for parsing public Instagram links into downloadable media.",
    version="0.1.0",
)

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS - only allows the configured frontend origin(s)
configure_cors(app)

# Routes
app.include_router(health.router)
app.include_router(fetch.router)
app.include_router(bundle.router)
app.include_router(streaming.router)


@app.get("/")
def root():
    return {"service": settings.app_name, "docs": "/docs", "health": "/health"}


# ---------------------------------------------------------------------------
# Global exception handling.
#
# Anything that escapes a route (an unexpected yt-dlp/httpx exception, a bug,
# a timeout deep in a dependency) lands here instead of turning into a raw
# 500 with a stack trace, or — for a hung extraction — a request that never
# resolves. Known, expected errors (HTTPException raised deliberately in a
# route, request validation errors) keep their original status codes and
# messages; only truly unexpected exceptions get the generic message below.
# ---------------------------------------------------------------------------


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"detail": "Invalid request body.", "errors": exc.errors()},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Something went wrong processing that request. Please try again."},
    )
