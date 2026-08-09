import logging

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.deps import (
    get_analysis_service,
    get_company_lookup_service,
    get_current_user,
    get_email_service,
)
from app.core.exceptions import BadRequestError, NotFoundError
from app.core.rate_limit import analyze_rate_limiter, suggest_cache, suggest_rate_limiter
from app.models.schemas import (
    AnalyzeRequest,
    ClearHistoryResponse,
    CompanyAnalysisListItem,
    CompanyAnalysisResponse,
    EmailBriefRequest,
    EmailBriefResponse,
    ExpandInsightRequest,
    ExpandInsightResponse,
    HealthResponse,
    ResolveCompanyRequest,
    ResolveCompanyResponse,
    SuggestCompaniesResponse,
)
from app.models.user import User
from app.services.analysis_service import AnalysisService
from app.services.company_lookup_service import CompanyLookupService
from app.services.email_service import EmailService

logger = logging.getLogger(__name__)
router = APIRouter()


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


@router.get("/health", response_model=HealthResponse)
def health(db: Session = Depends(get_db)) -> HealthResponse:
    settings = get_settings()
    # Readiness: ensure DB is reachable
    db.execute(text("SELECT 1"))
    return HealthResponse(status="ok", app=settings.app_name, environment=settings.environment)


@router.get("/companies/suggest", response_model=SuggestCompaniesResponse)
def suggest_companies(
    request: Request,
    q: str = Query(..., min_length=2, max_length=200),
    lookup: CompanyLookupService = Depends(get_company_lookup_service),
) -> SuggestCompaniesResponse:
    """Lightweight autocomplete while typing (no auth; rate-limited + cached)."""
    cleaned = " ".join(q.strip().split())
    client = _client_ip(request)
    suggest_rate_limiter.check(f"suggest-ip:{client}", limit=60, window_seconds=60)

    cache_key = f"suggest:{cleaned.lower()}"
    cached = suggest_cache.get(cache_key)
    if isinstance(cached, list):
        return SuggestCompaniesResponse(query=cleaned, suggestions=cached)

    items = lookup.suggest(cleaned, limit=6)
    payload = [
        {
            "name": item.name,
            "description": item.description,
            "confidence": item.confidence,
            "source": item.source,
            "ticker": item.ticker,
            "location": item.location,
        }
        for item in items
    ]
    # Don't pin empty misses for long — near-miss fixes / upstream recovery should retry soon.
    suggest_cache.set(cache_key, payload, ttl_seconds=20 if not payload else 120)
    logger.info("Company suggest query=%r suggestions=%s ip=%s", cleaned, len(payload), client)
    return SuggestCompaniesResponse.model_validate({"query": cleaned, "suggestions": payload})


@router.post("/companies/resolve", response_model=ResolveCompanyResponse)
def resolve_company(
    payload: ResolveCompanyRequest,
    user: User = Depends(get_current_user),
    lookup: CompanyLookupService = Depends(get_company_lookup_service),
) -> ResolveCompanyResponse:
    resolution = lookup.resolve(payload.query)
    logger.info(
        "Company resolve query=%r status=%s confidence=%.3f suggestions=%s user_id=%s",
        resolution.query,
        resolution.status,
        resolution.confidence,
        len(resolution.suggestions),
        user.id,
    )
    return ResolveCompanyResponse.model_validate(lookup.to_dict(resolution))


@router.post("/analyze", response_model=CompanyAnalysisResponse)
async def analyze_company(
    payload: AnalyzeRequest,
    request: Request,
    user: User = Depends(get_current_user),
    service: AnalysisService = Depends(get_analysis_service),
    email_service: EmailService = Depends(get_email_service),
    lookup: CompanyLookupService = Depends(get_company_lookup_service),
) -> CompanyAnalysisResponse:
    settings = get_settings()
    client = _client_ip(request)

    logger.info(
        "Analyze requested company=%r force_refresh=%s send_email=%s ip=%s user_id=%s",
        payload.company_name,
        payload.force_refresh,
        payload.send_email,
        client,
        user.id,
    )

    # Confidence gate: only high-confidence exact company names proceed to insights.
    # Exception: user explicitly picked a suggestion card (confirmed=True) — still
    # re-resolve so given-name pages cannot bypass via autocomplete.
    if payload.confirmed:
        company_name = payload.company_name
        logger.info("Analyze confirmed suggestion company=%r user_id=%s", company_name, user.id)
        resolution = lookup.resolve(company_name)
        if resolution.status != "exact" or not resolution.matched_name:
            raise BadRequestError(
                resolution.message or "No valid companies found with this name."
            )
        company_name = resolution.matched_name
    else:
        resolution = lookup.resolve(payload.company_name)
        if resolution.status != "exact" or not resolution.matched_name:
            if resolution.status == "ambiguous" and resolution.suggestions:
                names = ", ".join(item.name for item in resolution.suggestions[:5])
                raise BadRequestError(
                    f"{resolution.message} Suggestions: {names}."
                )
            raise BadRequestError(resolution.message or "No valid companies found with this name.")
        company_name = resolution.matched_name

    # Cache hits are free (no NewsAPI / LLM). Only throttle paths that hit upstream.
    if not payload.force_refresh:
        cached = service.peek_cache(company_name, user_id=user.id)
        if cached:
            logger.info("Analyze cache hit company=%r id=%s", cached.company_name, cached.id)
            return cached

    analyze_rate_limiter.check(
        f"analyze-ip:{client}",
        limit=settings.analyze_rate_limit,
        window_seconds=settings.analyze_rate_window_seconds,
    )
    # Private sessions get a tighter per-user budget on top of the shared IP limit.
    if user.is_guest:
        analyze_rate_limiter.check(
            f"analyze-guest:{user.id}",
            limit=settings.guest_analyze_rate_limit,
            window_seconds=settings.analyze_rate_window_seconds,
        )

    result = await service.analyze(
        company_name,
        force_refresh=payload.force_refresh,
        user_id=user.id,
        confirmed=payload.confirmed,
        identity_verified=True,
    )
    logger.info(
        "Analyze completed company=%r id=%s cached=%s model=%s",
        result.company_name,
        result.id,
        result.cached,
        result.llm_model,
    )

    should_email = (payload.send_email or settings.email_auto_send) and not user.is_guest
    if payload.send_email and user.is_guest:
        raise BadRequestError("Email brief requires a signed-in account.")
    if should_email:
        row = service.get_by_id(result.id, user_id=user.id)
        if row:
            # Explicit send_email raises on failure; auto-send only logs
            try:
                recipient = await email_service.send_analysis_async(row, to_email=payload.email_to)
                logger.info("Emailed brief id=%s to=%s", result.id, recipient)
            except Exception:
                if payload.send_email:
                    raise
                logger.exception("Auto-email failed id=%s", result.id)

    return result


@router.post("/analyses/{analysis_id}/expand", response_model=ExpandInsightResponse)
async def expand_insight(
    analysis_id: int,
    payload: ExpandInsightRequest,
    user: User = Depends(get_current_user),
    service: AnalysisService = Depends(get_analysis_service),
) -> ExpandInsightResponse:
    return await service.expand_insight(
        analysis_id,
        user_id=user.id,
        kind=payload.kind,
        index=payload.index,
        depth=payload.depth,
        prior_analysis=payload.prior_analysis,
    )


@router.post("/analyses/{analysis_id}/email", response_model=EmailBriefResponse)
async def email_analysis(
    analysis_id: int,
    payload: EmailBriefRequest | None = None,
    user: User = Depends(get_current_user),
    service: AnalysisService = Depends(get_analysis_service),
    email_service: EmailService = Depends(get_email_service),
) -> EmailBriefResponse:
    if user.is_guest:
        raise BadRequestError("Email brief requires a signed-in account.")

    row = service.get_by_id(analysis_id, user_id=user.id)
    if not row:
        raise NotFoundError("Analysis not found")

    to_email = payload.to if payload and payload.to else None
    recipient = await email_service.send_analysis_async(row, to_email=to_email)
    return EmailBriefResponse(
        status="sent",
        to=recipient,
        analysis_id=row.id,
        company_name=row.company_name,
    )


@router.get("/analyses", response_model=list[CompanyAnalysisListItem])
def list_analyses(
    limit: int = Query(default=20, ge=1, le=100),
    user: User = Depends(get_current_user),
    service: AnalysisService = Depends(get_analysis_service),
) -> list[CompanyAnalysisListItem]:
    rows = service.list_recent(limit=limit, user_id=user.id)
    logger.info("Listed recent analyses count=%s limit=%s user_id=%s", len(rows), limit, user.id)
    return [CompanyAnalysisListItem.model_validate(row, from_attributes=True) for row in rows]


@router.delete("/analyses", response_model=ClearHistoryResponse)
def clear_analyses(
    user: User = Depends(get_current_user),
    service: AnalysisService = Depends(get_analysis_service),
) -> ClearHistoryResponse:
    deleted = service.clear_history(user_id=user.id)
    return ClearHistoryResponse(status="cleared", deleted=deleted)


@router.get("/analyses/search", response_model=list[CompanyAnalysisListItem])
def search_analyses(
    q: str = Query(..., min_length=1, max_length=200),
    limit: int = Query(default=20, ge=1, le=100),
    user: User = Depends(get_current_user),
    service: AnalysisService = Depends(get_analysis_service),
) -> list[CompanyAnalysisListItem]:
    rows = service.search(q, limit=limit, user_id=user.id)
    logger.info("Search analyses q=%r matches=%s user_id=%s", q, len(rows), user.id)
    return [CompanyAnalysisListItem.model_validate(row, from_attributes=True) for row in rows]


@router.get("/analyses/{analysis_id}", response_model=CompanyAnalysisResponse)
def get_analysis(
    analysis_id: int,
    user: User = Depends(get_current_user),
    service: AnalysisService = Depends(get_analysis_service),
) -> CompanyAnalysisResponse:
    row = service.get_by_id(analysis_id, user_id=user.id)
    if not row:
        raise NotFoundError("Analysis not found")
    logger.info("Fetched analysis id=%s company=%r user_id=%s", analysis_id, row.company_name, user.id)
    return CompanyAnalysisResponse.model_validate(row, from_attributes=True)
