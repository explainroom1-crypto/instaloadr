"""
Core link-resolution logic.
"""
import asyncio
import hashlib
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Literal, Optional
from urllib.parse import urlparse

import httpx
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
    audio_url: Optional[str] = None


class FetchResponse(BaseModel):
    source_url: str
    items: list[MediaItem]


def _mock_items(media_type: Optional[str]) -> list[dict]:
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
    try:
        import yt_dlp
    except ImportError as exc:
        raise RuntimeError(
            "yt-dlp is not installed. Add it to requirements.txt and reinstall."
        ) from exc

    settings = get_settings()

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "socket_timeout": timeout,
        "ignore_no_formats_error": True,
        "cookiefile": getattr(settings, "cookies_file", None) or None,
        "format": "best",
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
        audio_url = None

        if formats:
            muxed = [
                f for f in formats
                if f.get("vcodec") not in (None, "none") and f.get("acodec") not in (None, "none")
            ]
            if muxed:
                best_format = max(muxed, key=lambda f: (f.get("height") or 0))
                best = best_format.get("url", best)
                width = best_format.get("width", width)
                height = best_format.get("height", height)
            else:
                video_only = [f for f in formats if f.get("vcodec") not in (None, "none")]
                audio_only = [
                    f for f in formats
                    if f.get("acodec") not in (None, "none") and f.get("vcodec") in (None, "none")
                ]
                if video_only:
                    best_video = max(video_only, key=lambda f: (f.get("height") or 0))
                    best = best_video.get("url", best)
                    width = best_video.get("width", width)
                    height = best_video.get("height", height)
                if audio_only:
                    best_audio = max(audio_only, key=lambda f: (f.get("abr") or 0))
                    audio_url = best_audio.get("url")
        elif entry.get("thumbnail"):
            best = entry.get("thumbnail")
            entry["ext"] = "jpg"

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
                "audio_url": audio_url,
            }
        )
    return items


async def _extract_profile_pic(url: str, timeout: int) -> list[dict]:
    parsed = urlparse(url)
    path_parts = [p for p in parsed.path.split("/") if p]
    if not path_parts:
        raise ValueError("Couldn't find a username in that profile link.")
    username = path_parts[0]

    profile_url = f"https://www.instagram.com/{username}/"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }

    async with httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=True) as client:
        resp = await client.get(profile_url)
        resp.raise_for_status()
        html = resp.text

    match = re.search(r'<meta property="og:image" content="([^"]+)"', html)
    if not match:
        raise ValueError("Couldn't find a profile picture for that account.")

    image_url = match.group(1).replace("&amp;", "&")

    return [
        {
            "media_type": "jpg",
            "download_url": image_url,
            "thumbnail_url": image_url,
            "width": None,
            "height": None,
            "duration": None,
            "audio_url": None,
        }
    ]


@router.post("/fetch", response_model=FetchResponse)
@limiter.limit(lambda: f"{get_settings().download_rate_limit_per_minute}/minute")
async def fetch_media(payload: FetchRequest, request: Request):
    settings = get_settings()

    if settings.mock_mode:
        raw_items = _mock_items(payload.media_type)
        return FetchResponse(source_url=payload.url, items=[MediaItem(**item) for item in raw_items])

    if payload.media_type == "dp":
        cache_key = _cache_key(payload.url, payload.media_type)
        cached = _fetch_cache.get(cache_key) if settings.fetch_cache_ttl_seconds > 0 else None
        if cached is not None:
            return FetchResponse(source_url=payload.url, items=[MediaItem(**item) for item in cached])

        try:
            raw_items = await _extract_profile_pic(payload.url, settings.request_timeout_seconds)
        except Exception as exc:
            raise HTTPException(
                status_code=422,
                detail="Couldn't find a profile picture for that link.",
            ) from exc

        if settings.fetch_cache_ttl_seconds > 0:
            _fetch_cache.set(cache_key, raw_items)

        return FetchResponse(source_url=payload.url, items=[MediaItem(**item) for item in raw_items])

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
        raise HTTPException(
            status_code=422,
            detail="Couldn't resolve that link. It may be private or expired.",
        ) from exc

    if not raw_items:
        raise HTTPException(status_code=404, detail="No downloadable media found.")

    if settings.fetch_cache_ttl_seconds > 0:
        _fetch_cache.set(cache_key, raw_items)

    return FetchResponse(source_url=payload.url, items=[MediaItem(**item) for item in raw_items])
