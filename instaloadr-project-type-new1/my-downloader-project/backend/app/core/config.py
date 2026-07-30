"""
Environment-driven settings for the backend.

All values can be overridden via environment variables (or a .env file
in local development). See backend/README.md for the full list.

This module is the *only* place environment-specific behavior (like
what CORS origins are trusted) should be decided. Routes and other
modules should never hardcode a domain or `"*"` — they should read it
from here.
"""
from enum import Enum
from functools import lru_cache
from typing import List, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(str, Enum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # General
    app_name: str = "Instagram Downloader API"
    environment: Environment = Environment.DEVELOPMENT
    debug: bool = False

    # --- CORS -----------------------------------------------------------
    # Comma-separated list of extra allowed origins, e.g.
    # "https://mydomain.com,https://www.mydomain.com". This is ADDITIVE
    # on top of the environment-based defaults below — you almost always
    # want to set this in production rather than relying on defaults.
    cors_allowed_origins: str = ""

    # --- Rate limiting (see core/security.py) ---------------------------
    # General default, applied to any route without its own explicit limit.
    rate_limit_per_minute: int = 30
    # Stricter limit specifically for the heavy, scraping-backed endpoints
    # (/api/fetch, /api/bundle) — these are the ones that actually cost you
    # in outbound bandwidth/proxy usage and are the ones bots would hammer.
    download_rate_limit_per_minute: int = 5

    # --- Networking / extraction -----------------------------------------
    request_timeout_seconds: int = 20
    max_items_per_request: int = 20

    # --- Result caching -----------------------------------------------------
    # How long a resolved link's result is reused before re-extracting.
    # Purely a performance/reliability optimization (see core/cache.py) —
    # set to 0 to disable caching entirely.
    fetch_cache_ttl_seconds: int = 300
    fetch_cache_max_entries: int = 500

    # Optional path to a cookies.txt file (Netscape format) exported from
    # an Instagram account YOU control. Only needed for content that
    # requires a logged-in session (e.g. your own Stories). Leave unset
    # for public post/reel extraction.
    cookies_file: Optional[str] = "cookies.txt"

    # --- Mock mode --------------------------------------------------------
    # When true, /api/fetch skips real extraction entirely and returns a
    # canned response. Use this to stand up the full request path (CORS,
    # headers, routing, rate limiting) end-to-end across environments
    # before wiring up real scraping. Should always be False in production.
    mock_mode: bool = False

    # --- Derived / environment-aware helpers -------------------------------

    @property
    def is_production(self) -> bool:
        return self.environment == Environment.PRODUCTION

    @property
    def cors_origins_list(self) -> List[str]:
        """
        Resolve the final list of allowed CORS origins for this environment.

        - development: permissive by default (local file servers, Live
          Server, etc. run on unpredictable ports), plus anything extra
          you set in CORS_ALLOWED_ORIGINS.
        - staging/production: NEVER falls back to "*". You must set
          CORS_ALLOWED_ORIGINS explicitly (e.g. your Cloudflare Pages /
          Vercel domain). If it's empty in production, we deliberately
          return an empty list rather than guessing — that fails closed
          instead of silently wide open.
        """
        extra = [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]

        if self.environment == Environment.DEVELOPMENT:
            defaults = [
                "http://localhost:5500",
                "http://127.0.0.1:5500",
                "http://localhost:3000",
                "http://127.0.0.1:3000",
            ]
            # dedupe while preserving order
            return list(dict.fromkeys(defaults + extra))

        # staging / production: explicit only, no wildcard fallback
        return extra


@lru_cache
def get_settings() -> Settings:
    """Cached settings instance — import and call this, don't instantiate Settings() directly."""
    return Settings()
