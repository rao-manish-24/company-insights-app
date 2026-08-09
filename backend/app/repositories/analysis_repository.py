from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.company import CompanyAnalysis


def normalize_company_name(name: str) -> str:
    return " ".join(name.strip().lower().split())


class AnalysisRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_id(self, analysis_id: int, *, user_id: int | None = None) -> CompanyAnalysis | None:
        row = self.db.get(CompanyAnalysis, analysis_id)
        if not row:
            return None
        if user_id is not None and row.user_id != user_id:
            return None
        return row

    def list_recent(self, limit: int = 20, *, user_id: int) -> list[CompanyAnalysis]:
        stmt = (
            select(CompanyAnalysis)
            .where(CompanyAnalysis.user_id == user_id)
            .order_by(CompanyAnalysis.created_at.desc())
            .limit(limit)
        )
        return list(self.db.scalars(stmt).all())

    def search(self, query: str, limit: int = 20, *, user_id: int) -> list[CompanyAnalysis]:
        # Escape LIKE wildcards so user input is treated literally
        escaped = (
            normalize_company_name(query)
            .replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
        )
        pattern = f"%{escaped}%"
        stmt = (
            select(CompanyAnalysis)
            .where(CompanyAnalysis.user_id == user_id)
            .where(CompanyAnalysis.company_name_normalized.ilike(pattern, escape="\\"))
            .order_by(CompanyAnalysis.created_at.desc())
            .limit(limit)
        )
        return list(self.db.scalars(stmt).all())

    def get_cached(
        self,
        company_name: str,
        cache_hours: int,
        *,
        user_id: int,
    ) -> CompanyAnalysis | None:
        normalized = normalize_company_name(company_name)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=cache_hours)
        stmt = (
            select(CompanyAnalysis)
            .where(CompanyAnalysis.user_id == user_id)
            .where(CompanyAnalysis.company_name_normalized == normalized)
            .where(CompanyAnalysis.created_at >= cutoff)
            .order_by(CompanyAnalysis.created_at.desc())
            .limit(1)
        )
        return self.db.scalars(stmt).first()

    def save(self, record: CompanyAnalysis) -> CompanyAnalysis:
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return record

    def delete_all(self, *, user_id: int) -> int:
        result = self.db.execute(
            delete(CompanyAnalysis).where(CompanyAnalysis.user_id == user_id)
        )
        self.db.commit()
        return int(result.rowcount or 0)
