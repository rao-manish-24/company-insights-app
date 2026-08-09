"""In-memory rate limiting and singleflight coalescing (single-process)."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, TypeVar

from app.core.exceptions import AppError

logger = logging.getLogger(__name__)

T = TypeVar("T")


class RateLimitError(AppError):
    status_code = 429
    default_detail = "Rate limit exceeded. Please retry shortly."


@dataclass
class _CacheEntry:
    value: Any
    expires_at: float
    stale_until: float


class TtlCache:
    """Simple process-local TTL cache with optional stale-while-revalidate reads."""

    def __init__(self) -> None:
        self._store: dict[str, _CacheEntry] = {}

    def get(self, key: str, *, allow_stale: bool = False) -> Any | None:
        entry = self._store.get(key)
        if not entry:
            return None
        now = time.time()
        if now >= entry.stale_until:
            self._store.pop(key, None)
            return None
        if now < entry.expires_at:
            return entry.value
        # Soft-expired: keep for stale-while-revalidate callers only.
        return entry.value if allow_stale else None

    def set(self, key: str, value: Any, ttl_seconds: int, *, stale_seconds: int | None = None) -> None:
        now = time.time()
        soft = max(1, int(ttl_seconds))
        hard = soft + max(0, int(stale_seconds if stale_seconds is not None else soft * 3))
        self._store[key] = _CacheEntry(
            value=value,
            expires_at=now + soft,
            stale_until=now + hard,
        )


class SlidingWindowRateLimiter:
    """Per-key sliding window limiter."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str, *, limit: int, window_seconds: int) -> None:
        if limit <= 0:
            return
        now = time.time()
        bucket = self._hits[key]
        cutoff = now - window_seconds
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= limit:
            retry_after = max(1, int(window_seconds - (now - bucket[0])))
            raise RateLimitError(
                f"Too many requests. Try again in about {retry_after}s."
            )
        bucket.append(now)


class SingleFlight:
    """Coalesce concurrent identical async work into one execution."""

    def __init__(self) -> None:
        self._inflight: dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()

    async def do(self, key: str, factory: Callable[[], Awaitable[T]]) -> T:
        async with self._lock:
            existing = self._inflight.get(key)
            if existing is not None:
                logger.info("Singleflight join key=%s", key)
                task = existing
            else:
                task = asyncio.create_task(factory())
                self._inflight[key] = task

        try:
            return await asyncio.shield(task)
        finally:
            async with self._lock:
                current = self._inflight.get(key)
                if current is task:
                    self._inflight.pop(key, None)


# Shared process singletons
news_cache = TtlCache()
profile_cache = TtlCache()
market_cache = TtlCache()
analyze_singleflight = SingleFlight()
analyze_rate_limiter = SlidingWindowRateLimiter()
refresh_rate_limiter = SlidingWindowRateLimiter()
suggest_rate_limiter = SlidingWindowRateLimiter()
suggest_cache = TtlCache()
guest_rate_limiter = SlidingWindowRateLimiter()
