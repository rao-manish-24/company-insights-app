import logging

from fastapi import APIRouter, Depends

from app.core.deps import get_auth_service, get_current_user
from app.models.schemas import AuthResponse, LoginRequest, RegisterRequest, UserPublic
from app.models.user import User
from app.services.auth_service import AuthService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


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


@router.get("/me", response_model=UserPublic)
def me(user: User = Depends(get_current_user)) -> UserPublic:
    return UserPublic.model_validate(user, from_attributes=True)
