from collections.abc import Generator

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.repositories.analysis_repository import AnalysisRepository
from app.services.analysis_service import AnalysisService
from app.services.email_service import EmailService
from app.services.insights_agent import InsightsAgent
from app.services.news_service import NewsService


def get_news_service() -> NewsService:
    return NewsService()


def get_insights_agent() -> InsightsAgent:
    return InsightsAgent()


def get_email_service() -> EmailService:
    return EmailService()


def get_analysis_repository(db: Session = Depends(get_db)) -> AnalysisRepository:
    return AnalysisRepository(db)


def get_analysis_service(
    db: Session = Depends(get_db),
    news_service: NewsService = Depends(get_news_service),
    insights_agent: InsightsAgent = Depends(get_insights_agent),
) -> AnalysisService:
    return AnalysisService(
        db=db,
        news_service=news_service,
        insights_agent=insights_agent,
    )


def get_db_session() -> Generator[Session, None, None]:
    yield from get_db()
