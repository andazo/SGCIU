from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ComplaintSubmission
from app.schemas import ComplaintSubmissionCreate


class IncidentNotFoundError(LookupError):
    pass


class IncidentService:
    def __init__(self, db: Session):
        self.db = db

    def create(self, payload: ComplaintSubmissionCreate) -> ComplaintSubmission:
        incident = ComplaintSubmission(
            name=payload.name,
            email=str(payload.email) if payload.email else None,
            phone=payload.phone,
            ai_extracted_data=payload.ai_extracted_data.model_dump(),
            ai_summary_text=payload.ai_summary_text,
            analysis_metadata=payload.analysis_metadata,
            requires_human_review=payload.requires_human_review,
            review_reason=payload.review_reason,
            model_name=payload.model_name,
            prompt_version=payload.prompt_version,
            truth_confirmation=payload.truth_confirmation,
            data_usage_consent=payload.data_usage_consent,
        )
        self.db.add(incident)
        self.db.commit()
        self.db.refresh(incident)
        return incident

    def get(self, incident_id: int) -> ComplaintSubmission:
        incident = self.db.get(ComplaintSubmission, incident_id)
        if incident is None:
            raise IncidentNotFoundError(incident_id)
        return incident

    def list(
        self,
        *,
        district: str | None = None,
        category: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[ComplaintSubmission], int]:
        query = select(ComplaintSubmission)
        count_query = select(func.count()).select_from(ComplaintSubmission)
        if district:
            condition = ComplaintSubmission.ai_extracted_data["distrito"].as_string() == district
            query = query.where(condition)
            count_query = count_query.where(condition)
        if category:
            condition = (
                ComplaintSubmission.ai_extracted_data["categoria_preliminar"].as_string()
                == category
            )
            query = query.where(condition)
            count_query = count_query.where(condition)
        query = query.order_by(ComplaintSubmission.created_at.desc()).limit(limit).offset(offset)
        return list(self.db.scalars(query)), int(self.db.scalar(count_query) or 0)
