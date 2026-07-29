"""
A small in-memory TTL cache for /api/fetch results.

Why this exists
----------------
It's common for the same link to get pasted more than once in a short
window — someone double-clicks Download, refreshes the page, or a few
different visitors paste the same viral post within a few minutes of
each other. Re-running a full yt-dlp extraction for each of those is
pure waste: it's slower for the user, and it's an extra outbound
request to Instagram for information you already have.

This is a performance/reliability optimization, not an anti-detection
one — it doesn't change what gets requested or how, it just avoids
requesting the same thing twice in a row. Swap `TTLCache` for a Redis-
backed version (same interface) if you run more than one backend
instance, since this in-memory version is per-process only.
"""
import time
from threading import Lock
from typing import Any, Optional


class TTLCache:
    def __init__(self, ttl_seconds: int = 300, max_entries: int = 500):
        self._ttl = ttl_seconds
        self._max_entries = max_entries
        self._store: dict[str, tuple[float, Any]] = {}
        self._lock = Lock()

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            entry = self._store.get(key)
            if not entry:
                return None
            expires_at, value = entry
            if expires_at < time.monotonic():
                self._store.pop(key, None)
                return None
            return value

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            if len(self._store) >= self._max_entries:
                # Evict the single oldest entry rather than pulling in a
                # full LRU dependency for what is a soft, best-effort cache.
                oldest_key = min(self._store, key=lambda k: self._store[k][0], default=None)
                if oldest_key is not None:
                    self._store.pop(oldest_key, None)
            self._store[key] = (time.monotonic() + self._ttl, value)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def __len__(self) -> int:
        return len(self._store)
