from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class CompanyAnalysis(Base):
    __tablename__ = "company_analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True
    )
    company_name: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    company_name_normalized: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    executive_summary: Mapped[str] = mapped_column(Text, nullable=False)
    key_themes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    opportunities: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    risks: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    recommendations: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    conversation_starters: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    articles: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    company_profile: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    llm_model: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
