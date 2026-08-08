import asyncio
import logging
import time

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.rate_limit import RateLimitError, analyze_singleflight, refresh_rate_limiter
from app.models.company import CompanyAnalysis
from app.models.schemas import CompanyAnalysisResponse
from app.repositories.analysis_repository import AnalysisRepository, normalize_company_name
from app.services.insights_agent import InsightsAgent
from app.services.news_service import NewsService

logger = logging.getLogger(__name__)


class AnalysisService:
    def __init__(
        self,
        db: Session,
        news_service: NewsService | None = None,
        insights_agent: InsightsAgent | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.repo = AnalysisRepository(db)
        self.news_service = news_service or NewsService(self.settings)
        self.insights_agent = insights_agent or InsightsAgent(self.settings)

    def peek_cache(self, company_name: str) -> CompanyAnalysisResponse | None:
        cleaned_name = " ".join(company_name.strip().split())
        if not cleaned_name:
            return None
        cached = self.repo.get_cached(cleaned_name, self.settings.analysis_cache_hours)
        if not cached:
            return None
        return CompanyAnalysisResponse.model_validate(cached, from_attributes=True).model_copy(
            update={"cached": True}
        )

    async def analyze(self, company_name: str, force_refresh: bool = False) -> CompanyAnalysisResponse:
        cleaned_name = " ".join(company_name.strip().split())
        if not cleaned_name:
            raise ValueError("Company name is required")

        normalized = normalize_company_name(cleaned_name)

        if not force_refresh:
            cached = self.peek_cache(cleaned_name)
            if cached:
                logger.info(
                    "Cache hit company=%r analysis_id=%s age_window_hours=%s",
                    cleaned_name,
                    cached.id,
                    self.settings.analysis_cache_hours,
                )
                return cached
            logger.info("Cache miss company=%r", cleaned_name)
        else:
            # Protect upstream quotas: at most one refresh per company per cooldown window
            try:
                refresh_rate_limiter.check(
                    f"refresh:{normalized}",
                    limit=1,
                    window_seconds=max(60, self.settings.refresh_cooldown_minutes * 60),
                )
            except RateLimitError:
                latest = self.repo.get_cached(cleaned_name, max(self.settings.analysis_cache_hours, 24) * 7)
                # Allow one more upstream run if the only cached brief is a fallback
                # (e.g. LLM key was missing/failing on first generate, then fixed).
                is_fallback = bool(
                    latest
                    and (
                        latest.llm_model == "fallback-heuristic"
                        or str(latest.executive_summary or "").startswith("[Fallback mode")
                    )
                )
                if latest and not is_fallback:
                    logger.info(
                        "Refresh cooldown — serving cached brief company=%r id=%s",
                        cleaned_name,
                        latest.id,
                    )
                    return CompanyAnalysisResponse.model_validate(latest, from_attributes=True).model_copy(
                        update={"cached": True}
                    )
                if is_fallback:
                    logger.info(
                        "Refresh cooldown bypass — cached brief is fallback company=%r id=%s",
                        cleaned_name,
                        latest.id if latest else None,
                    )
                else:
                    raise RateLimitError(
                        f"Refresh cooldown active for {cleaned_name}. "
                        f"Try again in about {self.settings.refresh_cooldown_minutes} minutes."
                    )

        async def _run() -> CompanyAnalysisResponse:
            return await self._analyze_uncached(cleaned_name)

        return await analyze_singleflight.do(f"analyze:{normalized}", _run)

    async def _analyze_uncached(self, cleaned_name: str) -> CompanyAnalysisResponse:
        started = time.perf_counter()
        logger.info("Pipeline start company=%r (uncached)", cleaned_name)

        # Another coalesced waiter may have just finished writing the row
        cached = self.repo.get_cached(cleaned_name, self.settings.analysis_cache_hours)
        if cached:
            logger.info("Cache filled during wait company=%r analysis_id=%s", cleaned_name, cached.id)
            return CompanyAnalysisResponse.model_validate(cached, from_attributes=True).model_copy(
                update={"cached": True}
            )

        articles = await self.news_service.fetch_company_news(cleaned_name)
        logger.info("News fetched company=%r article_count=%s", cleaned_name, len(articles))

        insights = await asyncio.to_thread(self.insights_agent.analyze, cleaned_name, articles)
        used_fallback = bool(insights.pop("_fallback", False))
        model_name = "fallback-heuristic" if used_fallback else self.settings.llm_model

        logger.info(
            "Insights ready company=%r themes=%s opportunities=%s risks=%s fallback=%s",
            cleaned_name,
            len(insights.get("key_themes", [])),
            len(insights.get("opportunities", [])),
            len(insights.get("risks", [])),
            used_fallback,
        )

        record = CompanyAnalysis(
            company_name=cleaned_name,
            company_name_normalized=normalize_company_name(cleaned_name),
            executive_summary=insights["executive_summary"],
            key_themes=insights.get("key_themes", []),
            opportunities=insights.get("opportunities", []),
            risks=insights.get("risks", []),
            recommendations=insights.get("recommendations", []),
            conversation_starters=insights.get("conversation_starters", []),
            articles=[article.model_dump() for article in articles],
            llm_model=model_name,
        )
        record = self.repo.save(record)

        elapsed_ms = (time.perf_counter() - started) * 1000
        logger.info(
            "Pipeline complete company=%r analysis_id=%s model=%s elapsed_ms=%.1f",
            cleaned_name,
            record.id,
            record.llm_model,
            elapsed_ms,
        )

        return CompanyAnalysisResponse.model_validate(record, from_attributes=True).model_copy(
            update={"cached": False}
        )

    def get_by_id(self, analysis_id: int) -> CompanyAnalysis | None:
        return self.repo.get_by_id(analysis_id)

    def list_recent(self, limit: int = 20) -> list[CompanyAnalysis]:
        return self.repo.list_recent(limit=limit)

    def search(self, query: str, limit: int = 20) -> list[CompanyAnalysis]:
        return self.repo.search(query, limit=limit)
