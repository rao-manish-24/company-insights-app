import pytest

from app.core.exceptions import UnauthorizedError
from app.repositories.user_repository import GUEST_PASSWORD_SENTINEL
from app.services.auth_service import GUEST_EMAIL_DOMAIN, AuthService


class _FakeRepo:
    def __init__(self) -> None:
        self.created: list[dict] = []
        self._by_email: dict[str, object] = {}
        self._next_id = 1
        self.pruned = 0

    def get_by_email(self, email: str):
        return self._by_email.get(email.strip().lower())

    def create(self, *, email: str, password_hash: str, display_name=None, is_guest: bool = False):
        user = type(
            "User",
            (),
            {
                "id": self._next_id,
                "email": email,
                "password_hash": password_hash,
                "display_name": display_name,
                "is_guest": is_guest,
            },
        )()
        self._next_id += 1
        self.created.append(
            {
                "email": email,
                "display_name": display_name,
                "is_guest": is_guest,
                "password_hash": password_hash,
            }
        )
        self._by_email[email] = user
        return user

    def prune_stale_guests(self, *, older_than_hours: int) -> int:
        self.pruned = older_than_hours
        return 0


def test_create_guest_session_issues_guest_user_and_token(monkeypatch) -> None:
    service = AuthService.__new__(AuthService)
    service.repo = _FakeRepo()
    service.settings = type(
        "S",
        (),
        {
            "admin_email": "admin@example.com",
            "guest_jwt_expire_minutes": 1440,
            "guest_retention_hours": 48,
        },
    )()

    captured: dict = {}

    def _token(**kwargs):
        captured.update(kwargs)
        return "guest-token"

    monkeypatch.setattr("app.services.auth_service.create_access_token", _token)

    user, token = service.create_guest_session()
    assert token == "guest-token"
    assert user.is_guest is True
    assert user.display_name == "Private session"
    assert str(user.email).endswith(f"@{GUEST_EMAIL_DOMAIN}")
    assert service.repo.created[0]["is_guest"] is True
    assert service.repo.created[0]["password_hash"] == GUEST_PASSWORD_SENTINEL
    assert service.repo.pruned == 48
    assert captured.get("is_guest") is True
    assert captured.get("expire_minutes") == 1440


def test_login_rejects_guest_users(monkeypatch) -> None:
    service = AuthService.__new__(AuthService)
    guest = type(
        "User",
        (),
        {
            "id": 9,
            "email": f"guest_abc@{GUEST_EMAIL_DOMAIN}",
            "password_hash": GUEST_PASSWORD_SENTINEL,
            "is_guest": True,
        },
    )()
    service.repo = type("R", (), {"get_by_email": lambda self, email: guest})()
    service.settings = type(
        "S",
        (),
        {"admin_email": "admin@example.com", "admin_username": "admin"},
    )()
    monkeypatch.setattr("app.services.auth_service.verify_password", lambda *_: True)

    with pytest.raises(UnauthorizedError, match="Invalid email or password"):
        service.login(email=guest.email, password="anything")
