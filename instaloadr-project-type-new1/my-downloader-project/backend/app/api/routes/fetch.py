"""
Core link-resolution logic.

Design notes
------------
Rather than hand-rolling calls against Instagram's private/internal
endpoints (which breaks frequently and is the main way these tools get
blocked or banned), this route delegates extraction to `yt-dlp`, a
widely used, actively maintained open-source extractor that already
implements Instagram support and is kept up to date by a large
community as Instagram's frontend changes.

Limits you should know about, honestly:
- Only genuinely public posts/reels are reliably extractable without
  authentication. Instagram routinely requires a logged-in session to
  serve Stories (and sometimes reels/posts too, depending on rollout),
  even for public accounts. If you need that, set `cookies_file` in
  config to a cookies.txt exported from an account YOU control, used
  only to fetch YOUR OWN content or content you have explicit rights
  to save. Do not use shared/scraped credentials.
- This project does not attempt to bypass login walls, rate limits, or
  anti-bot protections beyond what yt-dlp's public extractor already
  does for public content. Respect Instagram's Terms of Service and
  applicable copyright law in how you operate this service.
"""
import asyncio
import hashlib
from concurrent.futures import ThreadPoolExecutor
from typing import Literal, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, field_validator

from app.core.cache import TTLCache
from app.core.config import get_settings
from app.core.security import limiter

router = APIRouter(prefix="/api", tags=["fetch"])
_executor = ThreadPoolExecutor(max_workers=4)
_settings_for_cache = get_settings()
_fetch_cache = TTLCache(
    ttl_seconds=_settings_for_cache.fetch_cache_ttl_seconds,
    max_entries=_settings_for_cache.fetch_cache_max_entries,
)

ALLOWED_HOSTS = {"instagram.com", "www.instagram.com"}


def _cache_key(url: str, media_type: Optional[str]) -> str:
    raw = f"{media_type or ''}:{url.strip().lower()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class FetchRequest(BaseModel):
    url: str
    media_type: Optional[Literal["post", "video", "reel", "story", "dp", "audio"]] = None

    @field_validator("url")
    @classmethod
    def validate_instagram_url(cls, value: str) -> str:
        parsed = urlparse(value.strip())
        if parsed.scheme not in ("http", "https") or parsed.netloc not in ALLOWED_HOSTS:
            raise ValueError("Only instagram.com links are accepted.")
        return value.strip()


class MediaItem(BaseModel):
    media_type: str
    download_url: str
    thumbnail_url: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    duration: Optional[float] = None


class FetchResponse(BaseModel):
    source_url: str
    items: list[MediaItem]


def _mock_items(media_type: Optional[str]) -> list[dict]:
    """
    Canned response used when settings.mock_mode is True.

    Purpose: let you deploy frontend + backend end-to-end (Cloudflare/
    Vercel <-> Render) and verify CORS, headers, rate limiting, and
    routing all work across real networks — without touching yt-dlp or
    Instagram at all. Swap mock_mode off once that's confirmed and
    you're ready to test real extraction.
    """
    kind = media_type or "post"
    placeholder_img = "https://placehold.co/720x900/1e2430/edeae0?text=MOCK+FRAME"
    placeholder_video = "https://www.w3schools.com/html/mov_bbb.mp4"

    if kind == "story":
        return [
            {
                "media_type": "jpg",
                "download_url": placeholder_img,
                "thumbnail_url": placeholder_img,
                "width": 1080,
                "height": 1920,
                "duration": None,
            }
        ]

    if kind == "reel":
        return [
            {
                "media_type": "mp4",
                "download_url": placeholder_video,
                "thumbnail_url": placeholder_img,
                "width": 1080,
                "height": 1920,
                "duration": 12.4,
            }
        ]

    if kind == "video":
        return [
            {
                "media_type": "mp4",
                "download_url": placeholder_video,
                "thumbnail_url": placeholder_img,
                "width": 1080,
                "height": 1350,
                "duration": 22.0,
            }
        ]

    if kind == "dp":
        return [
            {
                "media_type": "jpg",
                "download_url": placeholder_img,
                "thumbnail_url": placeholder_img,
                "width": 320,
                "height": 320,
                "duration": None,
            }
        ]

    if kind == "audio":
        placeholder_audio = "https://www.w3schools.com/html/horse.mp3"
        return [
            {
                "media_type": "mp3",
                "download_url": placeholder_audio,
                "thumbnail_url": placeholder_img,
                "width": None,
                "height": None,
                "duration": 9.6,
            }
        ]

    # "post" — mock a 2-item carousel so the frontend's grid layout gets exercised too
    return [
        {
            "media_type": "jpg",
            "download_url": placeholder_img,
            "thumbnail_url": placeholder_img,
            "width": 1080,
            "height": 1350,
            "duration": None,
        },
        {
            "media_type": "mp4",
            "download_url": placeholder_video,
            "thumbnail_url": placeholder_img,
            "width": 1080,
            "height": 1350,
            "duration": 8.2,
        },
    ]


def _extract_sync(url: str, max_items: int, timeout: int, media_type: Optional[str] = None) -> list[dict]:
    """Runs yt-dlp extraction in a worker thread (yt-dlp is blocking)."""
    try:
        import yt_dlp
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "yt-dlp is not installed. Add it to requirements.txt and reinstall."
        ) from exc

    settings = get_settings()

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "socket_timeout": timeout,
        # If you're extracting content that requires being logged in
        # (e.g. your own Stories), point this at a cookies.txt file
        # exported from an account you control. Never use scraped or
        # shared credentials here.
        "cookiefile": getattr(settings, "cookies_file", None) or None,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    entries = info.get("entries") if info.get("_type") == "playlist" else [info]
    items = []
    for entry in entries[:max_items]:
        if not entry:
            continue
        formats = entry.get("formats") or []
        best = entry.get("url")
        width = entry.get("width")
        height = entry.get("height")

        if media_type == "audio":
            # Instagram typically muxes audio into the video container
            # rather than exposing a separate audio-only stream, so
            # "extraction" here means: pick the smallest video format
            # that still has the audio, and let the client (or a
            # ffmpeg step you add) pull the track out. If yt-dlp *does*
            # find a genuine audio-only format for a given link, prefer it.
            audio_only = [f for f in formats if f.get("vcodec") in (None, "none") and f.get("acodec") not in (None, "none")]
            if audio_only:
                best_format = max(audio_only, key=lambda f: (f.get("abr") or 0))
                items.append(
                    {
                        "media_type": "m4a",
                        "download_url": best_format.get("url", best),
                        "thumbnail_url": entry.get("thumbnail"),
                        "width": None,
                        "height": None,
                        "duration": entry.get("duration"),
                    }
                )
                continue
            # No standalone audio stream — fall through to normal video
            # selection below; the caller gets a video file, not a pure
            # audio file. Document this clearly rather than pretending
            # otherwise (see backend/README.md "Audio extraction" note).

        if formats:
            # Prefer the highest-resolution progressive format yt-dlp found.
            best_format = max(formats, key=lambda f: (f.get("height") or 0))
            best = best_format.get("url", best)
            width = best_format.get("width", width)
            height = best_format.get("height", height)

        if not best:
            continue

        items.append(
            {
                "media_type": entry.get("ext", "media"),
                "download_url": best,
                "thumbnail_url": entry.get("thumbnail"),
                "width": width,
                "height": height,
                "duration": entry.get("duration"),
            }
        )
    return items


@router.post("/fetch", response_model=FetchResponse)
@limiter.limit(lambda: f"{get_settings().download_rate_limit_per_minute}/minute")
async def fetch_media(payload: FetchRequest, request: Request):
    settings = get_settings()

    if settings.mock_mode:
        raw_items = _mock_items(payload.media_type)
        return FetchResponse(source_url=payload.url, items=[MediaItem(**item) for item in raw_items])

    if payload.media_type == "dp":
        # Profile-picture extraction needs a different code path than
        # yt-dlp's post/reel extractor (it's not a "post" URL at all —
        # it's the account's own avatar). Not built yet. Saying so
        # clearly here beats returning a confusing generic failure.
        raise HTTPException(
            status_code=501,
            detail="Profile picture downloads aren't implemented yet — coming soon.",
        )

    cache_key = _cache_key(payload.url, payload.media_type)
    cached = _fetch_cache.get(cache_key) if settings.fetch_cache_ttl_seconds > 0 else None
    if cached is not None:
        return FetchResponse(source_url=payload.url, items=[MediaItem(**item) for item in cached])

    try:
        loop = asyncio.get_event_loop()
        raw_items = await loop.run_in_executor(
            _executor,
            _extract_sync,
            payload.url,
            settings.max_items_per_request,
            settings.request_timeout_seconds,
            payload.media_type,
        )
    except Exception as exc:
        # Surface a clean, actionable error rather than a stack trace.
        raise HTTPException(
            status_code=422,
            detail=(
                "Couldn't resolve that link. It may be private, deleted, "
                "expired (Stories), or require a logged-in session."
            ),
        ) from exc

    if not raw_items:
        raise HTTPException(status_code=404, detail="No downloadable media found at that link.")

    if settings.fetch_cache_ttl_seconds > 0:
        _fetch_cache.set(cache_key, raw_items)

    return FetchResponse(source_url=payload.url, items=[MediaItem(**item) for item in raw_items])
