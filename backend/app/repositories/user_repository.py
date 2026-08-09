from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.company import CompanyAnalysis
from app.models.user import User

# Guests never log in with a password — skip bcrypt cost on every mint.
GUEST_PASSWORD_SENTINEL = "!guest-no-password"


class UserRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_id(self, user_id: int) -> User | None:
        return self.db.get(User, user_id)

    def get_by_email(self, email: str) -> User | None:
        normalized = email.strip().lower()
        stmt = select(User).where(User.email == normalized).limit(1)
        return self.db.scalars(stmt).first()

    def create(
        self,
        *,
        email: str,
        password_hash: str,
        display_name: str | None = None,
        is_guest: bool = False,
    ) -> User:
        user = User(
            email=email.strip().lower(),
            password_hash=password_hash,
            display_name=(display_name.strip() if display_name else None) or None,
            is_guest=is_guest,
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def update_credentials(
        self,
        user: User,
        *,
        password_hash: str,
        display_name: str | None = None,
    ) -> User:
        user.password_hash = password_hash
        if display_name is not None:
            cleaned = display_name.strip()
            user.display_name = cleaned or None
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def prune_stale_guests(self, *, older_than_hours: int) -> int:
        """Remove expired private sessions and their briefs."""
        if older_than_hours <= 0:
            return 0
        cutoff = datetime.now(timezone.utc) - timedelta(hours=older_than_hours)
        guests = list(
            self.db.scalars(
                select(User).where(User.is_guest.is_(True), User.created_at < cutoff)
            ).all()
        )
        if not guests:
            return 0
        guest_ids = [guest.id for guest in guests]
        self.db.execute(delete(CompanyAnalysis).where(CompanyAnalysis.user_id.in_(guest_ids)))
        for guest in guests:
            self.db.delete(guest)
        self.db.commit()
        return len(guest_ids)
