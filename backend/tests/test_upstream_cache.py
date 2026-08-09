from app.core.rate_limit import TtlCache


def test_ttl_cache_serves_stale_after_expiry() -> None:
    cache = TtlCache()
    cache.set("k", {"ok": True}, ttl_seconds=1, stale_seconds=60)
    assert cache.get("k") == {"ok": True}

    # Force soft expiry while keeping hard stale window.
    entry = cache._store["k"]  # noqa: SLF001
    entry.expires_at = 0
    assert cache.get("k") is None
    assert cache.get("k", allow_stale=True) == {"ok": True}
