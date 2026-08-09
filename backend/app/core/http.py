"""Shared pooled HTTP clients + per-host circuit breaking for free upstream APIs.

Two problems this solves:

1. Wikimedia (Wikipedia/Wikidata) returns a hard 403 for generic User-Agents.
   Their robot policy requires a contact URL or email in the UA string.
2. Building a new httpx.Client per request threw away the connection pool, so
   every upstream call paid a fresh TLS handshake.
"""

from __future__ import annotations

import logging
import threading
import time
from functools import lru_cache
from typing import Any

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

APP_VERSION = "1.2"

# Statuses that mean "this host is refusing us right now" — never a data problem.
_SOFT_FAIL_STATUSES = frozenset({403, 408, 409, 425, 429})


@lru_cache
def build_user_agent() -> str:
    """Wikimedia-compliant UA: product/version plus a way to contact us.

    https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_User-Agent_Policy
    """
    contact = (get_settings().upstream_contact or "").strip()
    if not contact:
        contact = "https://github.com/rao-manish-24/company-insights-app"
    return f"CompanyInsights/{APP_VERSION} ({contact}) python-httpx/{httpx.__version__}"


class HostCircuitBreaker:
    """Skip hosts that are actively refusing traffic instead of hammering them.

    Repeated 403/429s make free APIs throttle harder and add seconds of latency
    to every request, so a short cooldown is both kinder and faster.
    """

    def __init__(self, *, failure_threshold: int = 3, cooldown_seconds: int = 120) -> None:
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._failures: dict[str, int] = {}
        self._open_until: dict[str, float] = {}
        self._lock = threading.Lock()

    def is_open(self, host: str) -> bool:
        with self._lock:
            until = self._open_until.get(host)
            if until is None:
                return False
            if time.time() >= until:
                self._open_until.pop(host, None)
                self._failures.pop(host, None)
                return False
            return True

    def record_failure(self, host: str) -> None:
        with self._lock:
            count = self._failures.get(host, 0) + 1
            self._failures[host] = count
            if count >= self.failure_threshold and host not in self._open_until:
                self._open_until[host] = time.time() + self.cooldown_seconds
                logger.warning(
                    "Upstream circuit opened host=%s failures=%s cooldown=%ss",
                    host,
                    count,
                    self.cooldown_seconds,
                )

    def record_success(self, host: str) -> None:
        with self._lock:
            if host in self._failures or host in self._open_until:
                self._failures.pop(host, None)
                self._open_until.pop(host, None)

    def reset(self) -> None:
        with self._lock:
            self._failures.clear()
            self._open_until.clear()


upstream_breaker = HostCircuitBreaker()

_LIMITS = httpx.Limits(max_keepalive_connections=20, max_connections=60, keepalive_expiry=60.0)


@lru_cache
def get_http_client() -> httpx.Client:
    """Shared pooled client for normal upstream calls."""
    return httpx.Client(
        timeout=httpx.Timeout(15.0, connect=5.0),
        headers={"User-Agent": build_user_agent(), "Accept": "application/json"},
        follow_redirects=True,
        limits=_LIMITS,
    )


@lru_cache
def get_fast_http_client() -> httpx.Client:
    """Shared pooled client for latency-sensitive calls (autocomplete)."""
    return httpx.Client(
        timeout=httpx.Timeout(5.0, connect=3.0),
        headers={"User-Agent": build_user_agent(), "Accept": "application/json"},
        follow_redirects=True,
        limits=_LIMITS,
    )


def close_http_clients() -> None:
    for factory in (get_http_client, get_fast_http_client):
        if factory.cache_info().currsize:
            factory().close()
        factory.cache_clear()


def host_of(url: str) -> str:
    return httpx.URL(url).host


def get_json(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    client: httpx.Client | None = None,
    label: str = "upstream",
) -> dict[str, Any] | None:
    """GET JSON, returning None for any refusal/outage rather than raising.

    Callers treat None as "no data right now" and fall back to cache or other
    sources, so a throttled upstream degrades the brief instead of failing it.
    """
    host = host_of(url)
    if upstream_breaker.is_open(host):
        logger.info("Skipping %s — circuit open host=%s", label, host)
        return None

    http = client or get_http_client()
    try:
        response = http.get(url, params=params)
    except Exception:
        upstream_breaker.record_failure(host)
        logger.warning("%s request failed host=%s", label, host, exc_info=True)
        return None

    status = response.status_code
    if status in _SOFT_FAIL_STATUSES or status >= 500:
        upstream_breaker.record_failure(host)
        logger.warning(
            "%s soft-fail status=%s host=%s body=%s",
            label,
            status,
            host,
            response.text[:160].replace("\n", " "),
        )
        return None
    if status >= 400:
        logger.warning("%s client error status=%s host=%s", label, status, host)
        return None

    upstream_breaker.record_success(host)
    try:
        payload = response.json()
    except Exception:
        logger.warning("%s returned non-JSON host=%s", label, host, exc_info=True)
        return None
    return payload if isinstance(payload, dict) else {"_list": payload}
