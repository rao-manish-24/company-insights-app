from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import User


class UserRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_id(self, user_id: int) -> User | None:
        return self.db.get(User, user_id)

    def get_by_email(self, email: str) -> User | None:
        normalized = email.strip().lower()
        stmt = select(User).where(User.email == normalized).limit(1)
        return self.db.scalars(stmt).first()

    def create(self, *, email: str, password_hash: str, display_name: str | None = None) -> User:
        user = User(
            email=email.strip().lower(),
            password_hash=password_hash,
            display_name=(display_name.strip() if display_name else None) or None,
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
