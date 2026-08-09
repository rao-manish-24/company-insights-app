import re
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _validate_optional_email(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if not _EMAIL_RE.match(cleaned):
        raise ValueError("Invalid email address")
    return cleaned


class AnalyzeRequest(BaseModel):
    company_name: str = Field(..., min_length=2, max_length=200)
    force_refresh: bool = False
    send_email: bool = False
    email_to: str | None = None
    # True when the user picked a resolve suggestion — trust that name, don't re-ambiguate.
    confirmed: bool = False

    @field_validator("company_name")
    @classmethod
    def validate_company_name(cls, value: str) -> str:
        cleaned = " ".join(value.strip().split())
        if len(cleaned) < 2:
            raise ValueError("Not a valid company name. Enter at least 2 characters.")
        if not re.search(r"[A-Za-z]", cleaned):
            raise ValueError("Not a valid company name. Use letters in the company name.")
        return cleaned

    @field_validator("email_to")
    @classmethod
    def validate_email_to(cls, value: str | None) -> str | None:
        return _validate_optional_email(value)


class EmailBriefRequest(BaseModel):
    to: str | None = None

    @field_validator("to")
    @classmethod
    def validate_to(cls, value: str | None) -> str | None:
        return _validate_optional_email(value)


class EmailBriefResponse(BaseModel):
    status: str
    to: str
    analysis_id: int
    company_name: str


class NewsArticle(BaseModel):
    title: str
    description: str | None = None
    source: str | None = None
    url: str | None = None
    published_at: str | None = None


class CompanyAnalysisResponse(BaseModel):
    id: int
    company_name: str
    executive_summary: str
    key_themes: list[Any]
    opportunities: list[Any]
    risks: list[Any]
    recommendations: list[Any]
    conversation_starters: list[Any]
    articles: list[Any]
    company_profile: dict[str, Any] = Field(default_factory=dict)
    llm_model: str
    created_at: datetime
    cached: bool = False
    # Transient pipeline metrics (not persisted on the ORM row)
    elapsed_ms: float | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None

    model_config = {"from_attributes": True}

    @field_validator("company_profile", mode="before")
    @classmethod
    def default_company_profile(cls, value: Any) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}


class CompanyAnalysisListItem(BaseModel):
    id: int
    company_name: str
    executive_summary: str
    created_at: datetime

    model_config = {"from_attributes": True}


class RegisterRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=320)
    password: str = Field(..., min_length=8, max_length=128)
    display_name: str | None = Field(default=None, max_length=120)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if not _EMAIL_RE.match(cleaned):
            raise ValueError("Invalid email address")
        return cleaned


class LoginRequest(BaseModel):
    # Accepts email or bare username (e.g. admin → admin@companyinsights.local)
    email: str = Field(..., min_length=2, max_length=320)
    password: str = Field(..., min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def validate_login_identity(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if not cleaned:
            raise ValueError("Email or username is required")
        if "@" in cleaned:
            if not _EMAIL_RE.match(cleaned):
                raise ValueError("Invalid email address")
            return cleaned
        if not re.match(r"^[a-z0-9._-]{2,64}$", cleaned):
            raise ValueError("Invalid username")
        return cleaned


class UserPublic(BaseModel):
    id: int
    email: str
    display_name: str | None = None
    is_guest: bool = False
    created_at: datetime

    model_config = {"from_attributes": True}


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserPublic


class CompanySuggestionItem(BaseModel):
    name: str
    description: str | None = None
    confidence: float
    source: str
    ticker: str | None = None
    location: str | None = None


class ResolveCompanyRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=200)

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        cleaned = " ".join(value.strip().split())
        if len(cleaned) < 2:
            raise ValueError("Enter at least 2 characters.")
        return cleaned


class ResolveCompanyResponse(BaseModel):
    query: str
    status: str  # exact | ambiguous | not_found
    confidence: float
    matched_name: str | None = None
    message: str
    suggestions: list[CompanySuggestionItem] = Field(default_factory=list)


class SuggestCompaniesResponse(BaseModel):
    query: str
    suggestions: list[CompanySuggestionItem] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: str
    app: str
    environment: str


class ClearHistoryResponse(BaseModel):
    status: str
    deleted: int


class ExpandInsightRequest(BaseModel):
    kind: str = Field(..., pattern="^(opportunity|risk|recommendation)$")
    index: int = Field(..., ge=0, le=50)
    depth: str = Field(default="standard", pattern="^(standard|deep)$")
    prior_analysis: str | None = Field(default=None, max_length=8000)


class ExpandInsightSource(BaseModel):
    title: str
    source: str | None = None
    url: str | None = None
    published_at: str | None = None
    description: str | None = None


class SpotlightPoint(BaseModel):
    point: str
    explanation: str


class ExpandInsightResponse(BaseModel):
    kind: str
    index: int
    depth: str = "standard"
    heading: str
    deeper_analysis: str
    why_it_matters: str
    questions_to_ask: list[str] = Field(default_factory=list)
    suggested_moves: list[str] = Field(default_factory=list)
    detailed_narrative: str | None = None
    spotlight_points: list[SpotlightPoint] = Field(default_factory=list)
    sources: list[ExpandInsightSource] = Field(default_factory=list)
    fallback: bool = False
