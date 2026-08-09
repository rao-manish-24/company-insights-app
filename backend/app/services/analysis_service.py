import asyncio
import logging
import time

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.exceptions import NotFoundError
from app.core.rate_limit import RateLimitError, analyze_singleflight, refresh_rate_limiter
from app.models.company import CompanyAnalysis
from app.models.schemas import (
    CompanyAnalysisResponse,
    ExpandInsightResponse,
    ExpandInsightSource,
    NewsArticle,
    SpotlightPoint,
)
from app.repositories.analysis_repository import AnalysisRepository, normalize_company_name
from app.services.company_profile_service import CompanyProfileService, empty_profile
from app.services.insights_agent import InsightsAgent
from app.services.market_data_service import MarketDataService
from app.services.news_service import NewsService

logger = logging.getLogger(__name__)


def _merge_leadership(profile: dict, leadership_fill: dict | None) -> dict:
    if not isinstance(leadership_fill, dict):
        return profile
    people = list(profile.get("key_people") or [])
    by_role = {
        str(item.get("role")): item
        for item in people
        if isinstance(item, dict) and item.get("role")
    }
    for role in ("CFO", "CBO", "Vice President"):
        fill = leadership_fill.get(role)
        if not fill or not isinstance(fill, str):
            continue
        name = fill.strip()
        if not name or name.lower() in {"null", "none", "unknown", "n/a"}:
            continue
        existing = by_role.get(role)
        if existing and existing.get("name"):
            continue
        by_role[role] = {"role": role, "name": name}
    # Preserve stable order
    ordered_roles = ["CEO", "COO", "CFO", "CBO", "Vice President"]
    profile["key_people"] = [
        by_role.get(role) or {"role": role, "name": None} for role in ordered_roles
    ]
    return profile


def _cached_response(row: CompanyAnalysis) -> CompanyAnalysisResponse:
    return CompanyAnalysisResponse.model_validate(row, from_attributes=True).model_copy(
        update={
            "cached": True,
            "elapsed_ms": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }
    )


class AnalysisService:
    def __init__(
        self,
        db: Session,
        news_service: NewsService | None = None,
        insights_agent: InsightsAgent | None = None,
        profile_service: CompanyProfileService | None = None,
        market_service: MarketDataService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.repo = AnalysisRepository(db)
        self.news_service = news_service or NewsService(self.settings)
        self.insights_agent = insights_agent or InsightsAgent(self.settings)
        self.profile_service = profile_service or CompanyProfileService(self.settings)
        self.market_service = market_service or MarketDataService()

    def peek_cache(self, company_name: str, *, user_id: int) -> CompanyAnalysisResponse | None:
        cleaned_name = " ".join(company_name.strip().split())
        if not cleaned_name:
            return None
        cached = self.repo.get_cached(
            cleaned_name,
            self.settings.analysis_cache_hours,
            user_id=user_id,
        )
        if not cached:
            return None
        return _cached_response(cached)

    async def analyze(
        self,
        company_name: str,
        force_refresh: bool = False,
        *,
        user_id: int,
    ) -> CompanyAnalysisResponse:
        cleaned_name = " ".join(company_name.strip().split())
        if not cleaned_name:
            raise ValueError("Company name is required")

        normalized = normalize_company_name(cleaned_name)

        if not force_refresh:
            cached = self.peek_cache(cleaned_name, user_id=user_id)
            if cached:
                logger.info(
                    "Cache hit company=%r analysis_id=%s user_id=%s age_window_hours=%s",
                    cleaned_name,
                    cached.id,
                    user_id,
                    self.settings.analysis_cache_hours,
                )
                return cached
            logger.info("Cache miss company=%r user_id=%s", cleaned_name, user_id)
        else:
            # Protect upstream quotas: at most one refresh per company per cooldown window
            try:
                refresh_rate_limiter.check(
                    f"refresh:{user_id}:{normalized}",
                    limit=1,
                    window_seconds=max(60, self.settings.refresh_cooldown_minutes * 60),
                )
            except RateLimitError:
                latest = self.repo.get_cached(
                    cleaned_name,
                    max(self.settings.analysis_cache_hours, 24) * 7,
                    user_id=user_id,
                )
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
                        "Refresh cooldown — serving cached brief company=%r id=%s user_id=%s",
                        cleaned_name,
                        latest.id,
                        user_id,
                    )
                    return _cached_response(latest)
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
            return await self._analyze_uncached(
                cleaned_name,
                force_refresh=force_refresh,
                user_id=user_id,
            )

        return await analyze_singleflight.do(f"analyze:{user_id}:{normalized}", _run)

    async def _analyze_uncached(
        self,
        cleaned_name: str,
        *,
        force_refresh: bool = False,
        user_id: int,
    ) -> CompanyAnalysisResponse:
        started = time.perf_counter()
        logger.info(
            "Pipeline start company=%r force_refresh=%s user_id=%s",
            cleaned_name,
            force_refresh,
            user_id,
        )

        # Only reuse a brief written by a concurrent singleflight twin.
        # Never short-circuit a true Refresh against the long DB cache window.
        if not force_refresh:
            cached = self.repo.get_cached(
                cleaned_name,
                self.settings.analysis_cache_hours,
                user_id=user_id,
            )
            if cached:
                logger.info(
                    "Cache filled during wait company=%r analysis_id=%s user_id=%s",
                    cleaned_name,
                    cached.id,
                    user_id,
                )
                return _cached_response(cached)

        articles = await self.news_service.fetch_company_news(cleaned_name)
        logger.info("News fetched company=%r article_count=%s", cleaned_name, len(articles))

        profile, market = await asyncio.gather(
            asyncio.to_thread(self.profile_service.fetch_profile, cleaned_name),
            asyncio.to_thread(self.market_service.fetch_market, cleaned_name),
        )
        if not profile:
            profile = empty_profile()
        profile = self.market_service.apply_to_profile(profile, market)

        insights = await asyncio.to_thread(
            self.insights_agent.analyze,
            cleaned_name,
            articles,
            profile,
        )
        used_fallback = bool(insights.pop("_fallback", False))
        usage_raw = insights.pop("_usage", None)
        usage = usage_raw if isinstance(usage_raw, dict) else {}
        model_name = "fallback-heuristic" if used_fallback else self.settings.llm_model
        leadership_fill = insights.pop("leadership_fill", None)
        profile = _merge_leadership(profile, leadership_fill)

        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        completion_tokens = int(usage.get("completion_tokens") or 0)
        total_tokens = int(usage.get("total_tokens") or (prompt_tokens + completion_tokens))

        logger.info(
            "Insights ready company=%r themes=%s opportunities=%s risks=%s fallback=%s tokens=%s",
            cleaned_name,
            len(insights.get("key_themes", [])),
            len(insights.get("opportunities", [])),
            len(insights.get("risks", [])),
            used_fallback,
            total_tokens,
        )

        record = CompanyAnalysis(
            user_id=user_id,
            company_name=cleaned_name,
            company_name_normalized=normalize_company_name(cleaned_name),
            executive_summary=insights["executive_summary"],
            key_themes=insights.get("key_themes", []),
            opportunities=insights.get("opportunities", []),
            risks=insights.get("risks", []),
            recommendations=insights.get("recommendations", []),
            conversation_starters=insights.get("conversation_starters", []),
            articles=[article.model_dump() for article in articles],
            company_profile=profile,
            llm_model=model_name,
        )
        record = self.repo.save(record)

        elapsed_ms = (time.perf_counter() - started) * 1000
        logger.info(
            "Pipeline complete company=%r analysis_id=%s model=%s elapsed_ms=%.1f tokens=%s",
            cleaned_name,
            record.id,
            record.llm_model,
            elapsed_ms,
            total_tokens,
        )

        return CompanyAnalysisResponse.model_validate(record, from_attributes=True).model_copy(
            update={
                "cached": False,
                "elapsed_ms": round(elapsed_ms, 1),
                "prompt_tokens": prompt_tokens if total_tokens > 0 else None,
                "completion_tokens": completion_tokens if total_tokens > 0 else None,
                "total_tokens": total_tokens if total_tokens > 0 else None,
            }
        )

    def get_by_id(self, analysis_id: int, *, user_id: int) -> CompanyAnalysis | None:
        return self.repo.get_by_id(analysis_id, user_id=user_id)

    def list_recent(self, limit: int = 20, *, user_id: int) -> list[CompanyAnalysis]:
        return self.repo.list_recent(limit=limit, user_id=user_id)

    def search(self, query: str, limit: int = 20, *, user_id: int) -> list[CompanyAnalysis]:
        return self.repo.search(query, limit=limit, user_id=user_id)

    def clear_history(self, *, user_id: int) -> int:
        deleted = self.repo.delete_all(user_id=user_id)
        logger.info("Cleared analysis history deleted=%s user_id=%s", deleted, user_id)
        return deleted

    async def expand_insight(
        self,
        analysis_id: int,
        *,
        user_id: int,
        kind: str,
        index: int,
        depth: str = "standard",
        prior_analysis: str | None = None,
    ) -> ExpandInsightResponse:
        row = self.repo.get_by_id(analysis_id, user_id=user_id)
        if not row:
            raise NotFoundError("Analysis not found")

        collection_map = {
            "opportunity": list(row.opportunities or []),
            "risk": list(row.risks or []),
            "recommendation": list(row.recommendations or []),
        }
        collection = collection_map.get(kind) or []
        if index < 0 or index >= len(collection):
            raise NotFoundError("Insight item not found")

        raw_item = collection[index]
        item = raw_item if isinstance(raw_item, dict) else {}
        articles = [
            NewsArticle.model_validate(article)
            for article in (row.articles or [])
            if isinstance(article, dict)
        ]

        result = await asyncio.to_thread(
            self.insights_agent.expand_item,
            company_name=row.company_name,
            kind=kind,
            item=item,
            articles=articles,
            depth=depth,
            prior_analysis=prior_analysis,
        )

        sources = [
            ExpandInsightSource.model_validate(source)
            for source in (result.get("sources") or [])
            if isinstance(source, dict) and source.get("title")
        ]
        spotlight_points = [
            SpotlightPoint.model_validate(point)
            for point in (result.get("spotlight_points") or [])
            if isinstance(point, dict) and point.get("point") and point.get("explanation")
        ]

        logger.info(
            "Expanded insight analysis_id=%s kind=%s index=%s depth=%s sources=%s fallback=%s",
            analysis_id,
            kind,
            index,
            depth,
            len(sources),
            result.get("fallback"),
        )

        return ExpandInsightResponse(
            kind=kind,
            index=index,
            depth=depth,
            heading=str(result.get("heading") or item.get("title") or item.get("action") or ""),
            deeper_analysis=str(result.get("deeper_analysis") or ""),
            why_it_matters=str(result.get("why_it_matters") or ""),
            questions_to_ask=[str(q) for q in (result.get("questions_to_ask") or []) if q],
            suggested_moves=[str(m) for m in (result.get("suggested_moves") or []) if m],
            detailed_narrative=(
                str(result["detailed_narrative"]) if result.get("detailed_narrative") else None
            ),
            spotlight_points=spotlight_points,
            sources=sources,
            fallback=bool(result.get("fallback")),
        )
