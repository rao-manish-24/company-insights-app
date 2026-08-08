import asyncio
import logging
from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.core.exceptions import UpstreamError
from app.core.rate_limit import news_cache
from app.models.schemas import NewsArticle
from app.repositories.analysis_repository import normalize_company_name

logger = logging.getLogger(__name__)


class NewsServiceError(UpstreamError):
    default_detail = "Failed to fetch company news"


class NewsService:
    """Fetches recent company news from NewsAPI with TTL cache + 429 retries."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    async def fetch_company_news(self, company_name: str) -> list[NewsArticle]:
        cache_key = f"news:{normalize_company_name(company_name)}"
        cached = news_cache.get(cache_key)
        if cached is not None:
            logger.info(
                "News cache hit company=%r articles=%s ttl_minutes=%s",
                company_name,
                len(cached),
                self.settings.news_cache_minutes,
            )
            return cached

        if not self.settings.news_api_key:
            logger.warning("NEWS_API_KEY missing — returning demo articles for local/demo use")
            articles = self._demo_articles(company_name)
            news_cache.set(cache_key, articles, self.settings.news_cache_minutes * 60)
            return articles

        # Docs: https://newsapi.org/docs/endpoints/everything
        articles = await self._query(
            company_name,
            params={
                "q": f'"{company_name}"',
                "language": "en",
                "sortBy": "relevancy",
                "pageSize": self.settings.max_articles,
                "apiKey": self.settings.news_api_key,
            },
            mode="exact",
        )

        if not articles:
            logger.warning("No exact-match articles company=%r — trying broader query", company_name)
            articles = await self._query(
                company_name,
                params={
                    "q": company_name,
                    "language": "en",
                    "sortBy": "publishedAt",
                    "pageSize": self.settings.max_articles,
                    "apiKey": self.settings.news_api_key,
                },
                mode="broader",
            )

        news_cache.set(cache_key, articles, self.settings.news_cache_minutes * 60)
        logger.info("NewsAPI returned company=%r usable_articles=%s (cached)", company_name, len(articles))
        return articles

    async def _query(self, company_name: str, *, params: dict[str, Any], mode: str) -> list[NewsArticle]:
        url = f"{self.settings.news_api_base_url}/everything"
        logger.info("NewsAPI query company=%r mode=%s page_size=%s", company_name, mode, params.get("pageSize"))

        last_error: Exception | None = None
        for attempt in range(1, self.settings.news_max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.get(url, params=params)

                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", "2"))
                    wait_s = min(30, max(1, retry_after) * attempt)
                    logger.warning(
                        "NewsAPI rate limited company=%r attempt=%s wait_s=%s",
                        company_name,
                        attempt,
                        wait_s,
                    )
                    await asyncio.sleep(wait_s)
                    continue

                if response.status_code >= 500:
                    wait_s = min(20, 2 ** attempt)
                    logger.warning(
                        "NewsAPI server error %s company=%r attempt=%s wait_s=%s",
                        response.status_code,
                        company_name,
                        attempt,
                        wait_s,
                    )
                    await asyncio.sleep(wait_s)
                    continue

                response.raise_for_status()
                payload = response.json()

                if payload.get("status") != "ok":
                    message = payload.get("message", "Unknown NewsAPI error")
                    # NewsAPI sometimes returns rate messages in body with 200
                    if "rate" in message.lower() or "limit" in message.lower():
                        wait_s = min(30, 2 ** attempt)
                        logger.warning("NewsAPI quota message company=%r wait_s=%s msg=%s", company_name, wait_s, message)
                        await asyncio.sleep(wait_s)
                        continue
                    logger.error("NewsAPI error company=%r message=%s", company_name, message)
                    raise NewsServiceError(message)

                return self._parse_articles(payload.get("articles", []))

            except httpx.HTTPError as exc:
                last_error = exc
                wait_s = min(20, 2 ** attempt)
                logger.warning(
                    "NewsAPI HTTP error company=%r attempt=%s wait_s=%s err=%s",
                    company_name,
                    attempt,
                    wait_s,
                    exc,
                )
                await asyncio.sleep(wait_s)

        logger.error("NewsAPI exhausted retries company=%r", company_name)
        raise NewsServiceError(f"Failed to fetch news for {company_name}") from last_error

    @staticmethod
    def _parse_articles(raw_articles: list[dict[str, Any]]) -> list[NewsArticle]:
        articles: list[NewsArticle] = []
        for item in raw_articles:
            title = (item.get("title") or "").strip()
            if not title or title.lower() == "[removed]":
                continue
            articles.append(
                NewsArticle(
                    title=title,
                    description=item.get("description"),
                    source=(item.get("source") or {}).get("name"),
                    url=item.get("url"),
                    published_at=item.get("publishedAt"),
                )
            )
        return articles

    def _demo_articles(self, company_name: str) -> list[NewsArticle]:
        return [
            NewsArticle(
                title=f"{company_name} accelerates digital transformation initiatives",
                description=(
                    f"Analysts report that {company_name} is investing in cloud modernization "
                    "and AI-assisted operations to improve margins and customer experience."
                ),
                source="Industry Wire",
                url="https://example.com/digital-transformation",
                published_at="2026-08-01T09:00:00Z",
            ),
            NewsArticle(
                title=f"{company_name} faces margin pressure amid competitive pricing",
                description=(
                    f"Recent earnings commentary suggests {company_name} is navigating "
                    "cost inflation and aggressive competitor pricing in core markets."
                ),
                source="Market Daily",
                url="https://example.com/margin-pressure",
                published_at="2026-07-28T14:30:00Z",
            ),
            NewsArticle(
                title=f"Leadership changes signal new growth agenda at {company_name}",
                description=(
                    f"{company_name} appointed senior leaders focused on international expansion "
                    "and strategic partnerships across high-growth segments."
                ),
                source="Business Journal",
                url="https://example.com/leadership",
                published_at="2026-07-22T11:15:00Z",
            ),
            NewsArticle(
                title=f"Sustainability commitments expand across {company_name} supply chain",
                description=(
                    f"{company_name} outlined updated ESG targets, including supplier audits "
                    "and emissions reduction milestones through 2030."
                ),
                source="Green Business Review",
                url="https://example.com/esg",
                published_at="2026-07-18T08:45:00Z",
            ),
            NewsArticle(
                title=f"Investors watch {company_name} M&A pipeline for bolt-on deals",
                description=(
                    f"Market commentary highlights potential acquisitions that could "
                    f"strengthen {company_name}'s product portfolio and geographic reach."
                ),
                source="Deal Desk",
                url="https://example.com/manda",
                published_at="2026-07-12T16:20:00Z",
            ),
        ]
