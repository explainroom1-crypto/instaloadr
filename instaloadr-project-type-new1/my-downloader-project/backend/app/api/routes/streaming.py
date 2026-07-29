"""
GET /api/stream?url=... — proxies a single media file straight from
Instagram's CDN to the browser via chunked streaming. Bytes are never
buffered to disk or held fully in memory; each chunk is forwarded as
it arrives. Storage footprint on the server: 0.

This exists for the case where a CDN URL from yt-dlp's extraction
won't load directly in the browser (expired signed URL, referrer
checks, etc.) — the browser talks to *our* backend instead, and we
relay the bytes.

SSRF guard: this only proxies to known Instagram/Facebook CDN
hostnames. Without that allowlist, an endpoint like this becomes an
open proxy that will happily fetch ANY url on the caller's behalf —
that's a real vulnerability, not just a scraping concern.
"""
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.core.config import get_settings
from app.core.security import limiter

router = APIRouter(prefix="/api", tags=["stream"])

# Known Instagram/Facebook CDN host suffixes. Extend cautiously.
ALLOWED_CDN_SUFFIXES = (
    ".cdninstagram.com",
    ".fbcdn.net",
)


def _is_allowed_cdn_host(url: str) -> bool:
    try:
        host = urlparse(url).hostname or ""
    except ValueError:
        return False
    return any(host.endswith(suffix) for suffix in ALLOWED_CDN_SUFFIXES)


@router.get("/stream")
@limiter.limit(lambda: f"{get_settings().download_rate_limit_per_minute}/minute")
async def stream_media(request: Request, url: str = Query(..., description="A CDN URL returned by /api/fetch")):
    if not _is_allowed_cdn_host(url):
        raise HTTPException(status_code=400, detail="That URL isn't a recognized Instagram media host.")

    settings = get_settings()
    client = httpx.AsyncClient(timeout=settings.request_timeout_seconds)

    try:
        upstream = client.stream("GET", url)
        response = await upstream.__aenter__()
    except httpx.HTTPError:
        await client.aclose()
        raise HTTPException(status_code=502, detail="Couldn't reach the media host.")

    if response.status_code >= 400:
        await upstream.__aexit__(None, None, None)
        await client.aclose()
        raise HTTPException(status_code=502, detail="Media host returned an error for that file.")

    media_type = response.headers.get("content-type", "application/octet-stream")

    async def body_iterator():
        try:
            async for chunk in response.aiter_bytes():
                yield chunk
        finally:
            await upstream.__aexit__(None, None, None)
            await client.aclose()

    return StreamingResponse(body_iterator(), media_type=media_type)
