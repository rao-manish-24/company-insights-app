from collections.abc import Generator

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.exceptions import UnauthorizedError
from app.core.security import decode_access_token
from app.models.user import User
from app.repositories.analysis_repository import AnalysisRepository
from app.repositories.user_repository import UserRepository
from app.services.analysis_service import AnalysisService
from app.services.auth_service import AuthService
from app.services.email_service import EmailService
from app.services.insights_agent import InsightsAgent
from app.services.news_service import NewsService

_bearer = HTTPBearer(auto_error=False)


def get_news_service() -> NewsService:
    return NewsService()


def get_insights_agent() -> InsightsAgent:
    return InsightsAgent()


def get_email_service() -> EmailService:
    return EmailService()


def get_analysis_repository(db: Session = Depends(get_db)) -> AnalysisRepository:
    return AnalysisRepository(db)


def get_auth_service(db: Session = Depends(get_db)) -> AuthService:
    return AuthService(db)


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


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    if not credentials or credentials.scheme.lower() != "bearer" or not credentials.credentials:
        raise UnauthorizedError("Sign in to continue")
    payload = decode_access_token(credentials.credentials)
    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError) as exc:
        raise UnauthorizedError("Invalid token payload") from exc
    user = UserRepository(db).get_by_id(user_id)
    if not user:
        raise UnauthorizedError("Account not found")
    return user


def get_db_session() -> Generator[Session, None, None]:
    yield from get_db()
