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
    company_name: str = Field(..., min_length=1, max_length=200)
    force_refresh: bool = False
    send_email: bool = False
    email_to: str | None = None

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
