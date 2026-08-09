import logging

from fastapi import APIRouter, Depends, Request

from app.core.deps import get_auth_service, get_current_user
from app.core.rate_limit import guest_rate_limiter
from app.models.schemas import AuthResponse, LoginRequest, RegisterRequest, UserPublic
from app.models.user import User
from app.services.auth_service import AuthService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


def _client_ip(request: Request) -> str:
    forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    return forwarded or (request.client.host if request.client else "unknown")


@router.post("/register", response_model=AuthResponse)
def register(
    payload: RegisterRequest,
    service: AuthService = Depends(get_auth_service),
) -> AuthResponse:
    user, token = service.register(
        email=payload.email,
        password=payload.password,
        display_name=payload.display_name,
    )
    return AuthResponse(
        access_token=token,
        user=UserPublic.model_validate(user, from_attributes=True),
    )


@router.post("/login", response_model=AuthResponse)
def login(
    payload: LoginRequest,
    service: AuthService = Depends(get_auth_service),
) -> AuthResponse:
    user, token = service.login(email=payload.email, password=payload.password)
    return AuthResponse(
        access_token=token,
        user=UserPublic.model_validate(user, from_attributes=True),
    )


@router.post("/guest", response_model=AuthResponse)
def create_guest_session(
    request: Request,
    service: AuthService = Depends(get_auth_service),
) -> AuthResponse:
    client = _client_ip(request)
    guest_rate_limiter.check(f"guest-ip:{client}", limit=20, window_seconds=3600)
    user, token = service.create_guest_session()
    logger.info("Guest session issued id=%s ip=%s", user.id, client)
    return AuthResponse(
        access_token=token,
        user=UserPublic.model_validate(user, from_attributes=True),
    )


@router.get("/me", response_model=UserPublic)
def me(user: User = Depends(get_current_user)) -> UserPublic:
    return UserPublic.model_validate(user, from_attributes=True)
