import logging

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.exceptions import BadRequestError, ConflictError, UnauthorizedError
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.repositories.user_repository import UserRepository

logger = logging.getLogger(__name__)


class AuthService:
    def __init__(self, db: Session, settings: Settings | None = None) -> None:
        self.repo = UserRepository(db)
        self.settings = settings or get_settings()

    def ensure_admin_user(self) -> User:
        """Create or refresh the persistent admin account from env settings."""
        email = self.settings.admin_email.strip().lower()
        password = self.settings.admin_password
        display_name = self.settings.admin_display_name.strip() or "Admin"
        if not email or "@" not in email:
            raise BadRequestError("ADMIN_EMAIL must be a valid email")
        if len(password) < 8:
            raise BadRequestError("ADMIN_PASSWORD must be at least 8 characters")

        existing = self.repo.get_by_email(email)
        password_hash = hash_password(password)
        if existing:
            user = self.repo.update_credentials(
                existing,
                password_hash=password_hash,
                display_name=display_name,
            )
            logger.info("Admin account ensured id=%s email=%r", user.id, user.email)
            return user

        user = self.repo.create(
            email=email,
            password_hash=password_hash,
            display_name=display_name,
        )
        logger.info("Admin account created id=%s email=%r", user.id, user.email)
        return user

    def _resolve_login_email(self, identity: str) -> str:
        cleaned = identity.strip().lower()
        if "@" in cleaned:
            return cleaned
        if cleaned == self.settings.admin_username.strip().lower():
            return self.settings.admin_email.strip().lower()
        raise UnauthorizedError("Invalid email or password")

    def register(self, *, email: str, password: str, display_name: str | None = None) -> tuple[User, str]:
        cleaned_email = email.strip().lower()
        if len(password) < 8:
            raise BadRequestError("Password must be at least 8 characters")
        if cleaned_email == self.settings.admin_email.strip().lower():
            raise ConflictError("This account is reserved. Sign in with the admin credentials.")
        if self.repo.get_by_email(cleaned_email):
            raise ConflictError("An account with this email already exists")

        user = self.repo.create(
            email=cleaned_email,
            password_hash=hash_password(password),
            display_name=display_name,
        )
        token = create_access_token(user_id=user.id, email=user.email)
        logger.info("User registered id=%s email=%r", user.id, user.email)
        return user, token

    def login(self, *, email: str, password: str) -> tuple[User, str]:
        login_email = self._resolve_login_email(email)
        user = self.repo.get_by_email(login_email)
        if not user or not verify_password(password, user.password_hash):
            raise UnauthorizedError("Invalid email or password")
        token = create_access_token(user_id=user.id, email=user.email)
        logger.info("User logged in id=%s email=%r", user.id, user.email)
        return user, token
