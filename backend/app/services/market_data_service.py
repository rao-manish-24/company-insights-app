"""Fetch public market snapshot via Yahoo Finance (free, no API key)."""

from __future__ import annotations

import logging
import re
import time
from typing import Any

import httpx
import yfinance as yf

logger = logging.getLogger(__name__)

YAHOO_SEARCH = "https://query2.finance.yahoo.com/v1/finance/search"
YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
USER_AGENT = "CompanyInsights/1.1 (partner briefing prototype; educational use)"

_TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,11}$")


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
        self._client = httpx.Client(
            timeout=20.0,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        )

    def close(self) -> None:
        self._client.close()

    def fetch_market(self, company_name: str) -> dict[str, Any]:
        market = empty_market()
        cleaned = " ".join(company_name.strip().split())
        if not cleaned:
            return market

        try:
            ticker = self._resolve_ticker(cleaned)
            if not ticker:
                logger.info("Yahoo Finance: no ticker for company=%r", cleaned)
                return market

            info = self._fetch_info_bundle(ticker)
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
            return market
        except Exception:
            logger.exception("Yahoo Finance fetch failed company=%r", cleaned)
            return empty_market()

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
        compact = company_name.strip().upper().replace(" ", "")
        # Only treat short tokens as tickers (MSFT, BRK.B) — not full names.
        if _TICKER_RE.match(compact) and len(compact) <= 6 and " " not in company_name.strip():
            if self._chart_meta(compact):
                return compact

        quotes = self._search_quotes(company_name)
        preferred_types = {"EQUITY", "ETF"}
        ranked = [
            quote
            for quote in quotes
            if quote.get("symbol") and (quote.get("quoteType") or "").upper() in preferred_types
        ]
        if not ranked:
            ranked = [quote for quote in quotes if quote.get("symbol")]

        if ranked:
            name_l = company_name.lower()
            for quote in ranked:
                long_name = (quote.get("longname") or quote.get("shortname") or "").lower()
                if name_l in long_name or long_name in name_l:
                    return str(quote["symbol"])
            return str(ranked[0]["symbol"])

        guess = company_name.strip().upper().replace(" ", "-")
        if self._chart_meta(guess):
            return guess
        return None

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
            response.raise_for_status()
            return list(response.json().get("quotes") or [])
        except Exception:
            logger.exception("Yahoo search failed company=%r", company_name)
            return []

    def _fetch_info_bundle(self, ticker: str) -> dict[str, Any]:
        info = self._fetch_yfinance_info(ticker)
        chart = self._chart_meta(ticker) or {}

        if not info and not chart:
            return {}

        merged: dict[str, Any] = dict(info or {})
        # Chart fills price gaps when .info is rate-limited.
        if chart.get("regularMarketPrice") is not None and not merged.get("regularMarketPrice"):
            merged["regularMarketPrice"] = chart.get("regularMarketPrice")
        if chart.get("previousClose") is not None and not merged.get("previousClose"):
            merged["previousClose"] = chart.get("previousClose")
        if chart.get("chartPreviousClose") is not None and not merged.get("previousClose"):
            merged["previousClose"] = chart.get("chartPreviousClose")
        if chart.get("currency") and not merged.get("currency"):
            merged["currency"] = chart.get("currency")
        if chart.get("exchangeName") and not merged.get("fullExchangeName"):
            merged["fullExchangeName"] = chart.get("exchangeName")
        if chart.get("shortName") and not merged.get("shortName"):
            merged["shortName"] = chart.get("shortName")
        if chart.get("fiftyTwoWeekHigh") is not None and not merged.get("fiftyTwoWeekHigh"):
            merged["fiftyTwoWeekHigh"] = chart.get("fiftyTwoWeekHigh")
        if chart.get("fiftyTwoWeekLow") is not None and not merged.get("fiftyTwoWeekLow"):
            merged["fiftyTwoWeekLow"] = chart.get("fiftyTwoWeekLow")
        if chart.get("regularMarketVolume") is not None and not merged.get("regularMarketVolume"):
            merged["regularMarketVolume"] = chart.get("regularMarketVolume")
        return merged

    def _fetch_yfinance_info(self, ticker: str) -> dict[str, Any] | None:
        last_error: Exception | None = None
        for attempt in range(3):
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
                last_error = exc
                message = str(exc).lower()
                if "rate" in message or "too many" in message:
                    time.sleep(1.2 * (attempt + 1))
                    continue
                logger.exception("yfinance .info failed ticker=%s", ticker)
                return None
        logger.warning("yfinance .info rate-limited ticker=%s error=%s", ticker, last_error)
        return None

    def _chart_meta(self, ticker: str) -> dict[str, Any] | None:
        try:
            response = self._client.get(
                YAHOO_CHART.format(symbol=ticker),
                params={"interval": "1d", "range": "5d"},
            )
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
