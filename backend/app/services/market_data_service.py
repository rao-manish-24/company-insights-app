"""Fetch public market snapshot via Yahoo Finance (free, no API key)."""

from __future__ import annotations

import copy
import logging
import re
import time
from typing import Any

import yfinance as yf

from app.core.config import get_settings
from app.core.http import get_http_client
from app.core.rate_limit import market_cache

logger = logging.getLogger(__name__)

YAHOO_SEARCH = "https://query2.finance.yahoo.com/v1/finance/search"
YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"

_TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,11}$")

# Mega-cap fallbacks when Yahoo search is empty/rate-limited (common in free-tier bursts).
_KNOWN_TICKERS: dict[str, str] = {
    "apple": "AAPL",
    "apple inc": "AAPL",
    "microsoft": "MSFT",
    "microsoft corporation": "MSFT",
    "tesla": "TSLA",
    "tesla inc": "TSLA",
    "amazon": "AMZN",
    "amazon.com": "AMZN",
    "google": "GOOGL",
    "alphabet": "GOOGL",
    "alphabet inc": "GOOGL",
    "meta": "META",
    "meta platforms": "META",
    "nvidia": "NVDA",
    "netflix": "NFLX",
    "intel": "INTC",
    "ibm": "IBM",
    "oracle": "ORCL",
    "salesforce": "CRM",
    "adobe": "ADBE",
    "amd": "AMD",
    "advanced micro devices": "AMD",
    "siemens": "SIEGY",
    "siemens ag": "SIEGY",
    "nestle": "NSRGY",
    "nestlé": "NSRGY",
    "uber": "UBER",
    "airbnb": "ABNB",
    "spotify": "SPOT",
    "paypal": "PYPL",
    "visa": "V",
    "mastercard": "MA",
    "jpmorgan": "JPM",
    "jp morgan": "JPM",
    "goldman sachs": "GS",
    "morgan stanley": "MS",
    "accenture": "ACN",
}


def empty_market() -> dict[str, Any]:
    return {
        "ticker": None,
        "name": None,
        "exchange": None,
        "currency": None,
        "price": None,
        "previous_close": None,
        "change_percent": None,
        "market_cap": None,
        "pe_ratio": None,
        "forward_pe": None,
        "eps": None,
        "dividend_yield": None,
        "fifty_two_week_high": None,
        "fifty_two_week_low": None,
        "beta": None,
        "sector": None,
        "industry": None,
        "volume": None,
        "avg_volume": None,
        "source": None,
        "source_url": None,
    }


class MarketDataService:
    def __init__(self) -> None:
        self._client = get_http_client()
        # True when Yahoo throttled/blocked us (429/5xx) during the last fetch.
        self.last_degraded = False

    def close(self) -> None:
        """No-op: HTTP client is shared process-wide."""

    def fetch_market(self, company_name: str, *, ticker: str | None = None) -> dict[str, Any]:
        self.last_degraded = False
        market = empty_market()
        cleaned = " ".join(company_name.strip().split())
        if not cleaned:
            return market

        cache_key = f"market:{cleaned.lower()}"
        cached = market_cache.get(cache_key)
        if isinstance(cached, dict):
            logger.info("Yahoo Finance cache hit company=%r", cleaned)
            return copy.deepcopy(cached)

        try:
            hint = (ticker or "").strip().upper() or None
            if not hint and self._is_known_private(cleaned):
                logger.info("Yahoo Finance skipped for private company=%r", cleaned)
                return market
            if hint:
                ticker_cached = market_cache.get(f"market:ticker:{hint}")
                if isinstance(ticker_cached, dict):
                    logger.info("Yahoo Finance ticker cache hit ticker=%s", hint)
                    return self._store_market(cache_key, copy.deepcopy(ticker_cached))

            chart_hint = self._chart_meta(hint) if hint else None
            resolved = hint if hint and chart_hint else None
            ticker = resolved or self._resolve_ticker(cleaned)
            if not ticker:
                logger.info("Yahoo Finance: no ticker for company=%r", cleaned)
                stale = market_cache.get(cache_key, allow_stale=True)
                if isinstance(stale, dict):
                    logger.info("Yahoo Finance stale cache after empty ticker company=%r", cleaned)
                    return copy.deepcopy(stale)
                return market

            # With a validated ticker hint, chart-first avoids slow yfinance .info.
            info = self._fetch_info_bundle(
                ticker,
                light=bool(resolved),
                chart=chart_hint if resolved else None,
            )
            currency = (info.get("currency") if info else None) or "USD"
            price = None
            previous = None
            change_pct = None
            if info:
                price = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose")
                previous = info.get("previousClose") or info.get("regularMarketPreviousClose")
                change_pct = info.get("regularMarketChangePercent")
                if change_pct is None and price is not None and previous:
                    try:
                        change_pct = ((float(price) - float(previous)) / float(previous)) * 100
                    except (TypeError, ValueError, ZeroDivisionError):
                        change_pct = None

            market.update(
                {
                    "ticker": ticker,
                    "name": (info or {}).get("shortName") or (info or {}).get("longName"),
                    "exchange": (info or {}).get("exchange") or (info or {}).get("fullExchangeName"),
                    "currency": currency,
                    "price": self._format_price(price, currency),
                    "previous_close": self._format_price(previous, currency),
                    "change_percent": self._format_percent(change_pct),
                    "market_cap": self._format_money((info or {}).get("marketCap"), currency),
                    "pe_ratio": self._format_number((info or {}).get("trailingPE"), digits=2),
                    "forward_pe": self._format_number((info or {}).get("forwardPE"), digits=2),
                    "eps": self._format_price((info or {}).get("trailingEps"), currency),
                    "dividend_yield": self._format_yield((info or {}).get("dividendYield")),
                    "fifty_two_week_high": self._format_price(
                        (info or {}).get("fiftyTwoWeekHigh"), currency
                    ),
                    "fifty_two_week_low": self._format_price(
                        (info or {}).get("fiftyTwoWeekLow"), currency
                    ),
                    "beta": self._format_number((info or {}).get("beta"), digits=2),
                    "sector": (info or {}).get("sector"),
                    "industry": (info or {}).get("industry"),
                    "volume": self._format_shares(
                        (info or {}).get("volume") or (info or {}).get("regularMarketVolume")
                    ),
                    "avg_volume": self._format_shares((info or {}).get("averageVolume")),
                    "source": "Yahoo Finance",
                    "source_url": f"https://finance.yahoo.com/quote/{ticker}",
                }
            )

            if info:
                market["_fill_employees"] = self._format_employees(info.get("fullTimeEmployees"))
                market["_fill_revenue"] = self._format_money(info.get("totalRevenue"), currency)
                market["_fill_operating_income"] = self._format_money(
                    info.get("operatingIncome"), currency
                )
                market["_fill_hq"] = self._format_hq(info)

            logger.info(
                "Yahoo Finance market company=%r ticker=%s price=%s market_cap=%s",
                cleaned,
                ticker,
                market["price"],
                market["market_cap"],
            )
            stored = self._store_market(cache_key, market)
            if market.get("ticker"):
                market_cache.set(
                    f"market:ticker:{str(market['ticker']).upper()}",
                    copy.deepcopy(market),
                    max(60, get_settings().upstream_cache_minutes * 60),
                    stale_seconds=max(60, get_settings().upstream_cache_minutes * 60) * 3,
                )
            return stored
        except Exception:
            logger.exception("Yahoo Finance fetch failed company=%r", cleaned)
            stale = market_cache.get(cache_key, allow_stale=True)
            if isinstance(stale, dict):
                logger.info("Yahoo Finance stale cache after error company=%r", cleaned)
                return copy.deepcopy(stale)
            return empty_market()

    def _is_known_private(self, company_name: str) -> bool:
        # Imported lazily: the lookup service imports this module at load time.
        from app.services.company_lookup_service import KNOWN_PRIVATE_NAMES
        from app.services.company_validation import normalize_name

        return normalize_name(company_name) in KNOWN_PRIVATE_NAMES

    def _store_market(self, cache_key: str, market: dict[str, Any]) -> dict[str, Any]:
        if market.get("ticker"):
            ttl = max(60, get_settings().upstream_cache_minutes * 60)
            market_cache.set(cache_key, copy.deepcopy(market), ttl, stale_seconds=ttl * 3)
        return market

    def apply_to_profile(self, profile: dict[str, Any], market: dict[str, Any]) -> dict[str, Any]:
        if not market or not market.get("ticker"):
            return profile

        public = {key: value for key, value in market.items() if not key.startswith("_")}
        profile["market"] = public

        fills = (
            ("employees", market.get("_fill_employees")),
            ("revenue", market.get("_fill_revenue")),
            ("operating_income", market.get("_fill_operating_income")),
            ("headquarters", market.get("_fill_hq")),
        )
        for key, value in fills:
            if value and not profile.get(key):
                profile[key] = value

        return profile

    def _resolve_ticker(self, company_name: str) -> str | None:
        from app.services.company_validation import names_align, normalize_name

        compact = company_name.strip().upper().replace(" ", "")
        # Only treat short tokens as tickers (MSFT, BRK.B) — not full names.
        if _TICKER_RE.match(compact) and 1 < len(compact) <= 6 and " " not in company_name.strip():
            if self._chart_meta(compact):
                return compact

        search_terms = [company_name]
        tokens = company_name.strip().split()
        if len(tokens) >= 2:
            last = tokens[-1]
            low = last.lower()
            if len(low) > 3 and low.endswith("s") and not low.endswith(("ss", "us", "is", "oes")):
                search_terms.append(" ".join(tokens[:-1] + [last[:-1]]))
            elif len(low) > 2 and not low.endswith("s"):
                search_terms.append(" ".join(tokens[:-1] + [last + "s"]))

        quotes: list[dict[str, Any]] = []
        seen_symbols: set[str] = set()
        for term in search_terms:
            batch = self._search_quotes(term)
            if not batch and term == company_name:
                # One retry — Yahoo search often blips under free-tier pressure.
                time.sleep(0.35)
                batch = self._search_quotes(term)
            for quote in batch:
                symbol = str(quote.get("symbol") or "").upper()
                if not symbol or symbol in seen_symbols:
                    continue
                seen_symbols.add(symbol)
                quotes.append(quote)

        equities: list[dict[str, Any]] = []
        others: list[dict[str, Any]] = []
        for quote in quotes:
            if not quote.get("symbol"):
                continue
            if (quote.get("quoteType") or "").upper() == "EQUITY":
                equities.append(quote)
            else:
                others.append(quote)

        exact: list[dict[str, Any]] = []
        aligned: list[dict[str, Any]] = []
        # A symbol typed directly may match any instrument, including a fund.
        for quote in equities + others:
            symbol = str(quote.get("symbol") or "").upper()
            if compact and compact == symbol.replace(" ", ""):
                exact.append(quote)
        # A company name may only match an equity. Funds and ETFs are named after
        # their sponsor ("Fidelity Investment Grade Bond ETF"), so matching them by
        # name hands a private firm the ticker of its own fund.
        for quote in equities:
            symbol = str(quote.get("symbol") or "").upper()
            if compact and compact == symbol.replace(" ", ""):
                continue
            long_name = quote.get("longname") or quote.get("shortname") or ""
            if names_align(company_name, str(long_name)):
                # Prefer primary US listings (AAPL) over foreign duals (APC.DE, AAPL34.SA).
                aligned.append(quote)

        for quote in self._prefer_us_listing(exact) + self._prefer_us_listing(aligned):
            symbol = str(quote.get("symbol") or "")
            if symbol:
                return symbol

        # Last resort for mega-caps when search is empty/rate-limited.
        known = _KNOWN_TICKERS.get(normalize_name(company_name))
        if known and self._chart_meta(known):
            logger.info(
                "Yahoo Finance: using known ticker fallback company=%r ticker=%s",
                company_name,
                known,
            )
            return known
        return None

    @staticmethod
    def _prefer_us_listing(quotes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        def rank(quote: dict[str, Any]) -> tuple[int, int, str]:
            symbol = str(quote.get("symbol") or "")
            exchange = str(quote.get("exchange") or quote.get("exchDisp") or "").upper()
            us_ex = 0 if any(tag in exchange for tag in ("NMS", "NYQ", "NASDAQ", "NYSE", "NGM")) else 1
            # Prefer plain AAPL over AAPL.DE / AAPL34.SA
            simple = 0 if ("." not in symbol and not re.search(r"\d", symbol)) else 1
            return (us_ex, simple, symbol)

        return sorted(quotes, key=rank)

    def _search_quotes(self, company_name: str) -> list[dict[str, Any]]:
        try:
            response = self._client.get(
                YAHOO_SEARCH,
                params={
                    "q": company_name,
                    "quotesCount": 10,
                    "newsCount": 0,
                    "listsCount": 0,
                    "enableFuzzyQuery": "false",
                },
            )
            if response.status_code == 429 or response.status_code >= 500:
                logger.warning(
                    "Yahoo search soft-fail status=%s company=%r",
                    response.status_code,
                    company_name,
                )
                self.last_degraded = True
                return []
            response.raise_for_status()
            return list(response.json().get("quotes") or [])
        except Exception:
            logger.warning("Yahoo search failed company=%r", company_name, exc_info=True)
            self.last_degraded = True
            return []

    def _fetch_info_bundle(
        self,
        ticker: str,
        *,
        light: bool = False,
        chart: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        chart_meta = chart if chart is not None else (self._chart_meta(ticker) or {})
        # Light path: ticker already validated, so skip the slow .info round trip and
        # take the cheaper fast_info instead. The chart alone has no market cap, which
        # leaves the snapshot showing a price with no sense of the company's scale.
        # No fallback the other way: once .info is throttled, fast_info raises too.
        if light and chart_meta.get("regularMarketPrice") is not None:
            info: dict[str, Any] | None = self._fetch_yfinance_fast_info(ticker) or None
        else:
            info = self._fetch_yfinance_info(ticker)

        if not info and not chart_meta:
            return {}

        merged: dict[str, Any] = dict(info or {})
        # Chart fills price gaps when .info is rate-limited / skipped.
        if chart_meta.get("regularMarketPrice") is not None and not merged.get("regularMarketPrice"):
            merged["regularMarketPrice"] = chart_meta.get("regularMarketPrice")
        if chart_meta.get("previousClose") is not None and not merged.get("previousClose"):
            merged["previousClose"] = chart_meta.get("previousClose")
        if chart_meta.get("chartPreviousClose") is not None and not merged.get("previousClose"):
            merged["previousClose"] = chart_meta.get("chartPreviousClose")
        if chart_meta.get("currency") and not merged.get("currency"):
            merged["currency"] = chart_meta.get("currency")
        if chart_meta.get("exchangeName") and not merged.get("fullExchangeName"):
            merged["fullExchangeName"] = chart_meta.get("exchangeName")
        if chart_meta.get("shortName") and not merged.get("shortName"):
            merged["shortName"] = chart_meta.get("shortName")
        if chart_meta.get("fiftyTwoWeekHigh") is not None and not merged.get("fiftyTwoWeekHigh"):
            merged["fiftyTwoWeekHigh"] = chart_meta.get("fiftyTwoWeekHigh")
        if chart_meta.get("fiftyTwoWeekLow") is not None and not merged.get("fiftyTwoWeekLow"):
            merged["fiftyTwoWeekLow"] = chart_meta.get("fiftyTwoWeekLow")
        if chart_meta.get("regularMarketVolume") is not None and not merged.get(
            "regularMarketVolume"
        ):
            merged["regularMarketVolume"] = chart_meta.get("regularMarketVolume")
        return merged

    def _fetch_yfinance_info(self, ticker: str) -> dict[str, Any] | None:
        # One attempt only — retries under 429 make Yahoo throttle harder.
        try:
            data = yf.Ticker(ticker).info
            if isinstance(data, dict) and any(
                key in data
                for key in (
                    "regularMarketPrice",
                    "currentPrice",
                    "marketCap",
                    "shortName",
                    "longName",
                    "trailingPE",
                )
            ):
                return data
            return None
        except Exception as exc:
            message = str(exc).lower()
            if "rate" in message or "too many" in message:
                logger.warning("yfinance .info rate-limited ticker=%s", ticker)
                return None
            logger.warning("yfinance .info failed ticker=%s", ticker, exc_info=True)
            return None

    # fast_info keys → the .info keys the rest of this service already reads.
    _FAST_INFO_FIELDS: tuple[tuple[str, str], ...] = (
        ("regularMarketPrice", "lastPrice"),
        ("previousClose", "previousClose"),
        ("marketCap", "marketCap"),
        ("currency", "currency"),
        ("exchange", "exchange"),
        ("regularMarketVolume", "lastVolume"),
        ("fiftyTwoWeekHigh", "fiftyTwoWeekHigh"),
        ("fiftyTwoWeekLow", "fiftyTwoWeekLow"),
    )

    def _fetch_yfinance_fast_info(self, ticker: str) -> dict[str, Any]:
        bundle: dict[str, Any] = {}
        # Every read is lazy, so any key can raise once Yahoo throttles the process.
        try:
            fast = yf.Ticker(ticker).fast_info
            for target, source in self._FAST_INFO_FIELDS:
                value = fast.get(source)
                if value is not None:
                    bundle[target] = value
        except Exception as exc:
            if "rate" in str(exc).lower() or "too many" in str(exc).lower():
                logger.warning("yfinance fast_info rate-limited ticker=%s", ticker)
            else:
                logger.warning("yfinance fast_info failed ticker=%s", ticker, exc_info=True)
            return bundle
        logger.info("yfinance fast_info ticker=%s fields=%s", ticker, len(bundle))
        return bundle

    def _chart_meta(self, ticker: str) -> dict[str, Any] | None:
        try:
            response = self._client.get(
                YAHOO_CHART.format(symbol=ticker),
                params={"interval": "1d", "range": "5d"},
            )
            if response.status_code == 429 or response.status_code >= 500:
                logger.warning(
                    "Yahoo chart soft-fail status=%s ticker=%s",
                    response.status_code,
                    ticker,
                )
                return None
            response.raise_for_status()
            result = ((response.json().get("chart") or {}).get("result") or [None])[0]
            if not result:
                return None
            meta = result.get("meta") or {}
            return meta if meta.get("symbol") or meta.get("regularMarketPrice") is not None else None
        except Exception:
            logger.debug("Yahoo chart meta failed ticker=%s", ticker, exc_info=True)
            return None

    @staticmethod
    def _format_hq(info: dict[str, Any]) -> str | None:
        parts = [info.get("city"), info.get("state"), info.get("country")]
        cleaned = [str(part) for part in parts if part]
        return ", ".join(cleaned) if cleaned else None

    @staticmethod
    def _format_employees(value: Any) -> str | None:
        try:
            count = int(value)
        except (TypeError, ValueError):
            return None
        if count <= 0:
            return None
        return f"{count:,} employees"

    @staticmethod
    def _format_price(value: Any, currency: str) -> str | None:
        try:
            amount = float(value)
        except (TypeError, ValueError):
            return None
        return f"{amount:,.2f} {currency}"

    @staticmethod
    def _format_percent(value: Any) -> str | None:
        try:
            amount = float(value)
        except (TypeError, ValueError):
            return None
        if abs(amount) < 1:
            amount *= 100
        sign = "+" if amount > 0 else ""
        return f"{sign}{amount:.2f}%"

    @staticmethod
    def _format_yield(value: Any) -> str | None:
        try:
            amount = float(value)
        except (TypeError, ValueError):
            return None
        if amount <= 0:
            return None
        if amount < 1:
            amount *= 100
        return f"{amount:.2f}%"

    @staticmethod
    def _format_number(value: Any, *, digits: int = 2) -> str | None:
        try:
            amount = float(value)
        except (TypeError, ValueError):
            return None
        return f"{amount:.{digits}f}"

    @staticmethod
    def _format_shares(value: Any) -> str | None:
        try:
            amount = float(value)
        except (TypeError, ValueError):
            return None
        if amount <= 0:
            return None
        if amount >= 1_000_000_000:
            return f"{amount / 1_000_000_000:.2f}B"
        if amount >= 1_000_000:
            return f"{amount / 1_000_000:.2f}M"
        if amount >= 1_000:
            return f"{amount / 1_000:.2f}K"
        return f"{amount:,.0f}"

    @staticmethod
    def _format_money(value: Any, currency: str) -> str | None:
        try:
            amount = float(value)
        except (TypeError, ValueError):
            return None
        if amount == 0:
            return None
        abs_amount = abs(amount)
        sign = "-" if amount < 0 else ""
        if abs_amount >= 1_000_000_000_000:
            pretty = f"{sign}{abs_amount / 1_000_000_000_000:.2f} trillion"
        elif abs_amount >= 1_000_000_000:
            pretty = f"{sign}{abs_amount / 1_000_000_000:.2f} billion"
        elif abs_amount >= 1_000_000:
            pretty = f"{sign}{abs_amount / 1_000_000:.2f} million"
        else:
            pretty = f"{sign}{abs_amount:,.0f}"
        return f"{pretty} {currency}"
