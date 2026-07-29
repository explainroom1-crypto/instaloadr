"""
POST /api/bundle — download every media item from a link as a single
.zip, fetched concurrently so multi-photo carousels don't wait on
files one at a time (this is the "multi-threaded / fastest downloads"
feature — implemented as async concurrent I/O rather than literal
threads, which is the correct tool for network-bound work like this).

Re-uses the exact same resolution logic as /api/fetch (including mock
mode) so the two endpoints never disagree about what a link contains.
"""
import asyncio
import io
import zipfile
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.api.routes.fetch import FetchRequest, _extract_sync, _mock_items
from app.core.config import get_settings
from app.core.security import limiter

router = APIRouter(prefix="/api", tags=["bundle"])

_EXT_BY_MEDIA_TYPE = {
    "mp4": "mp4",
    "jpg": "jpg",
    "jpeg": "jpg",
    "png": "png",
    "webp": "webp",
    "mp3": "mp3",
    "m4a": "m4a",
}


async def _fetch_bytes(client: httpx.AsyncClient, url: str, timeout: int) -> Optional[bytes]:
    try:
        resp = await client.get(url, timeout=timeout, follow_redirects=True)
        resp.raise_for_status()
        return resp.content
    except httpx.HTTPError:
        return None


@router.post("/bundle")
@limiter.limit(lambda: f"{get_settings().download_rate_limit_per_minute}/minute")
async def bundle_media(payload: FetchRequest, request: Request):
    settings = get_settings()

    if settings.mock_mode:
        items = _mock_items(payload.media_type)
    elif payload.media_type == "dp":
        raise HTTPException(
            status_code=501,
            detail="Profile picture downloads aren't implemented yet — coming soon.",
        )
    else:
        loop = asyncio.get_event_loop()
        try:
            items = await loop.run_in_executor(
                None,
                _extract_sync,
                payload.url,
                settings.max_items_per_request,
                settings.request_timeout_seconds,
                payload.media_type,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=422,
                detail="Couldn't resolve that link for bundling.",
            ) from exc

    if not items:
        raise HTTPException(status_code=404, detail="No downloadable media found at that link.")

    # Fetch every file concurrently rather than one-at-a-time.
    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(
            *[_fetch_bytes(client, item["download_url"], settings.request_timeout_seconds) for item in items]
        )

    buffer = io.BytesIO()
    included = 0
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, (item, content) in enumerate(zip(items, results), start=1):
            if content is None:
                continue
            ext = _EXT_BY_MEDIA_TYPE.get(item.get("media_type", ""), "bin")
            zf.writestr(f"frame_{i:02d}.{ext}", content)
            included += 1

    if included == 0:
        raise HTTPException(status_code=502, detail="Found media but couldn't download any of the files.")

    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=loadr-download.zip"},
    )
