"""
GET /api/stream?url=... — proxies a single media file straight from
Instagram's CDN to the browser via chunked streaming. Bytes are never
buffered to disk or held fully in memory; each chunk is forwarded as
it arrives. Storage footprint on the server: 0.
This exists for the case where a CDN URL from yt-dlp's extraction
won't load directly in the browser (expired signed URL, referrer
checks, etc.) — the browser talks to *our* backend instead, and we
relay the bytes.

GET /api/stream-merged?video_url=...&audio_url=... — for the case
where Instagram serves video and audio as two SEPARATE streams (no
single file has both). This runs ffmpeg live, reading both remote
streams and muxing them into one MP4 on the fly, streamed straight to
the browser. Nothing is written to disk here either — ffmpeg reads
from the network and writes to its stdout pipe, which we forward
chunk by chunk.

SSRF guard: both endpoints only proxy to known Instagram/Facebook CDN
hostnames. Without that allowlist, an endpoint like this becomes an
open proxy that will happily fetch ANY url on the caller's behalf —
that's a real vulnerability, not just a scraping concern.
"""
import asyncio
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


@router.get("/stream-merged")
@limiter.limit(lambda: f"{get_settings().download_rate_limit_per_minute}/minute")
async def stream_merged(
    request: Request,
    video_url: str = Query(..., description="Video-only CDN URL"),
    audio_url: str = Query(..., description="Audio-only CDN URL"),
):
    """
    Used only when /api/fetch returned an item with a non-null
    audio_url — meaning Instagram split video and audio into two
    separate streams. This merges them with ffmpeg (already installed
    in the Dockerfile) and streams the combined MP4 back.

    `-movflags frag_keyframe+empty_moov` makes ffmpeg write a
    "fragmented" MP4, which can be streamed as it's produced. A normal
    MP4's index (moov atom) is written only at the very end, which
    doesn't work when we're piping output live instead of writing a
    complete file to disk first.
    """
    if not _is_allowed_cdn_host(video_url) or not _is_allowed_cdn_host(audio_url):
        raise HTTPException(status_code=400, detail="That URL isn't a recognized Instagram media host.")

    settings = get_settings()

    cmd = [
        "ffmpeg",
        "-loglevel", "error",
        "-timeout", str(settings.request_timeout_seconds * 1_000_000),  # ffmpeg wants microseconds
        "-i", video_url,
        "-timeout", str(settings.request_timeout_seconds * 1_000_000),
        "-i", audio_url,
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c", "copy",
        "-f", "mp4",
        "-movflags", "frag_keyframe+empty_moov",
        "pipe:1",
    ]

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="ffmpeg isn't available on the server.")

    # Peek at the first chunk so we can catch an immediate ffmpeg
    # failure (bad URL, expired CDN link, etc.) and return a clean
    # error instead of a 200 response with zero bytes.
    first_chunk = await process.stdout.read(65536)
    if not first_chunk:
        stderr = (await process.stderr.read()).decode(errors="ignore")
        await process.wait()
        raise HTTPException(
            status_code=502,
            detail="Couldn't merge audio and video for that file. The source links may have expired.",
        )

    async def body_iterator():
        try:
            yield first_chunk
            while True:
                chunk = await process.stdout.read(65536)
                if not chunk:
                    break
                yield chunk
        finally:
            if process.returncode is None:
                process.kill()
            await process.wait()

    return StreamingResponse(body_iterator(), media_type="video/mp4")
