import logging

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.deps import get_analysis_service, get_current_user, get_email_service
from app.core.exceptions import NotFoundError
from app.core.rate_limit import analyze_rate_limiter
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
)
from app.models.user import User
from app.services.analysis_service import AnalysisService
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


@router.post("/analyze", response_model=CompanyAnalysisResponse)
async def analyze_company(
    payload: AnalyzeRequest,
    request: Request,
    user: User = Depends(get_current_user),
    service: AnalysisService = Depends(get_analysis_service),
    email_service: EmailService = Depends(get_email_service),
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

    # Cache hits are free (no NewsAPI / LLM). Only throttle paths that hit upstream.
    if not payload.force_refresh:
        cached = service.peek_cache(payload.company_name, user_id=user.id)
        if cached:
            logger.info("Analyze cache hit company=%r id=%s", cached.company_name, cached.id)
            return cached

    analyze_rate_limiter.check(
        f"analyze-ip:{client}",
        limit=settings.analyze_rate_limit,
        window_seconds=settings.analyze_rate_window_seconds,
    )

    result = await service.analyze(
        payload.company_name,
        force_refresh=payload.force_refresh,
        user_id=user.id,
    )
    logger.info(
        "Analyze completed company=%r id=%s cached=%s model=%s",
        result.company_name,
        result.id,
        result.cached,
        result.llm_model,
    )

    should_email = payload.send_email or settings.email_auto_send
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
