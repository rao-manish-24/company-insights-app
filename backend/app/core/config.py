from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

def _resolve_env_file() -> str:
    here = Path(__file__).resolve()
    candidates = [
        here.parents[3] / ".env",  # repo root when running from monorepo
        here.parents[2] / ".env",  # backend/ locally or /app in Docker
        Path.cwd() / ".env",
    ]
    for path in candidates:
        if path.exists():
            return str(path)
    return ".env"


_ENV_FILE = _resolve_env_file()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Company Insights"
    environment: str = "development"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,http://127.0.0.1:3000"
    log_level: str = "INFO"
    # text = human-readable console logs; json = cloud-friendly structured logs
    log_format: str = "text"
    # Rotating file path; set empty to disable file logging
    log_file: str = "logs/companyinsights.log"
    log_max_bytes: int = 5_000_000
    log_backup_count: int = 5

    database_url: str = "postgresql://companyinsights:companyinsights@localhost:5432/companyinsights"

    news_api_key: str = ""
    news_api_base_url: str = "https://newsapi.org/v2"

    # OpenAI-compatible API (OpenAI, Groq, OpenRouter, xAI, etc.)
    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"

    max_articles: int = 8
    # Prefer cache to protect NewsAPI + LLM free-tier quotas
    analysis_cache_hours: int = 24
    news_cache_minutes: int = 60
    # Wikidata / Wikipedia / Yahoo — reuse across resolve + analyze
    upstream_cache_minutes: int = 120
    # API self-throttling (process-local)
    analyze_rate_limit: int = 20
    analyze_rate_window_seconds: int = 3600
    refresh_cooldown_minutes: int = 5
    llm_max_retries: int = 5
    news_max_retries: int = 4

    # Resend (HTTPS) — preferred on Render free tier (SMTP ports are blocked)
    # https://resend.com — free tier; use onboarding@resend.dev until a domain is verified
    resend_api_key: str = ""
    resend_from: str = "Company Insights <onboarding@resend.dev>"

    # SMTP email (Gmail App Password) — works locally; blocked on Render free web services
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_use_tls: bool = True
    smtp_use_ssl: bool = False
    email_to: str = ""
    email_auto_send: bool = False

    # Auth (HS256 JWT). Override JWT_SECRET in every non-local environment.
    jwt_secret: str = "dev-only-change-me-company-insights-jwt"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7
    # Private/guest sessions are shorter-lived than registered accounts.
    guest_jwt_expire_minutes: int = 60 * 24
    guest_analyze_rate_limit: int = 8
    guest_retention_hours: int = 48

    # Persistent admin account ensured on every API startup.
    # Sign in with ADMIN_USERNAME or ADMIN_EMAIL + ADMIN_PASSWORD.
    admin_username: str = "admin"
    admin_email: str = "admin@companyinsights.local"
    admin_password: str = "Admin123!"
    admin_display_name: str = "Admin"

    @field_validator("log_format")
    @classmethod
    def validate_log_format(cls, value: str) -> str:
        normalized = value.lower().strip()
        if normalized not in {"text", "json"}:
            raise ValueError("LOG_FORMAT must be 'text' or 'json'")
        return normalized

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
