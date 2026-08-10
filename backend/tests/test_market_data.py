"""Market snapshot must belong to the company, or be absent."""

import pytest

from app.core.rate_limit import market_cache
from app.services.company_profile_service import KEY_PEOPLE_ROLES, empty_profile
from app.services.market_data_service import MarketDataService

# Yahoo returns a private asset manager's own funds when searched by name.
FIDELITY_QUOTES = [
    {
        "symbol": "FIGXX",
        "quoteType": "MUTUALFUND",
        "longname": "Fidelity Investments Money Market Government Portfolio",
    },
    {
        "symbol": "FIGB",
        "quoteType": "ETF",
        "longname": "Fidelity Investment Grade Bond ETF",
        "exchange": "PCX",
    },
]

MICROSOFT_QUOTES = [
    {
        "symbol": "MSFT",
        "quoteType": "EQUITY",
        "longname": "Microsoft Corporation",
        "exchange": "NMS",
    },
    {
        "symbol": "MSFT.NE",
        "quoteType": "EQUITY",
        "longname": "Microsoft Corporation CDR",
        "exchange": "NEO",
    },
]


def _service(monkeypatch, quotes):
    service = MarketDataService()
    monkeypatch.setattr(service, "_search_quotes", lambda term: list(quotes))
    monkeypatch.setattr(service, "_chart_meta", lambda symbol: {"symbol": symbol})
    return service


def test_company_name_never_resolves_to_a_fund(monkeypatch) -> None:
    """A bond ETF carries the sponsor's name — it is not the sponsor's stock."""
    service = _service(monkeypatch, FIDELITY_QUOTES)
    assert service._resolve_ticker("Fidelity Investments") is None


def test_directly_typed_fund_symbol_still_resolves(monkeypatch) -> None:
    service = _service(monkeypatch, FIDELITY_QUOTES)
    assert service._resolve_ticker("FIGB") == "FIGB"


def test_equity_still_resolves_by_name(monkeypatch) -> None:
    service = _service(monkeypatch, MICROSOFT_QUOTES)
    assert service._resolve_ticker("Microsoft Corporation") == "MSFT"


def test_fetch_market_skips_yahoo_for_known_private_firm(monkeypatch) -> None:
    market_cache.clear()
    service = MarketDataService()
    searched: list[str] = []

    def _record(term: str) -> list:
        searched.append(term)
        return list(FIDELITY_QUOTES)

    monkeypatch.setattr(service, "_search_quotes", _record)
    market = service.fetch_market("Fidelity Investments")

    assert market["ticker"] is None
    assert searched == []


def test_privately_held_asset_managers_skip_market_lookup() -> None:
    service = MarketDataService()
    assert service._is_known_private("Fidelity Investments")
    assert service._is_known_private("The Vanguard Group")
    assert not service._is_known_private("Microsoft Corporation")


def test_light_path_reports_market_cap(monkeypatch) -> None:
    """The chart alone gives a price with no sense of the company's scale."""
    service = MarketDataService()
    monkeypatch.setattr(
        service,
        "_fetch_yfinance_info",
        lambda symbol: pytest.fail("light path must not call the slow .info endpoint"),
    )
    monkeypatch.setattr(
        service,
        "_fetch_yfinance_fast_info",
        lambda symbol: {"marketCap": 3_712_698_417_529, "currency": "USD"},
    )

    bundle = service._fetch_info_bundle(
        "MSFT", light=True, chart={"regularMarketPrice": 499.99}
    )

    assert bundle["marketCap"] == 3_712_698_417_529
    assert bundle["regularMarketPrice"] == 499.99


def test_throttled_info_does_not_retry_the_same_throttled_backend(monkeypatch) -> None:
    """Once Yahoo throttles the process, fast_info raises too — don't waste the call."""
    service = MarketDataService()
    fast_calls: list[str] = []
    monkeypatch.setattr(service, "_fetch_yfinance_info", lambda symbol: None)
    monkeypatch.setattr(
        service, "_fetch_yfinance_fast_info", lambda symbol: fast_calls.append(symbol) or {}
    )

    bundle = service._fetch_info_bundle("MSFT", chart={"regularMarketPrice": 499.99})

    assert fast_calls == []
    assert bundle["regularMarketPrice"] == 499.99


def test_profile_exposes_ceo_only() -> None:
    assert KEY_PEOPLE_ROLES == ("CEO",)
    assert [person["role"] for person in empty_profile()["key_people"]] == ["CEO"]
