from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ComplaintSubmission, HumanReview
from app.schemas import ComplaintSubmissionCreate

logger = logging.getLogger(__name__)


class IncidentNotFoundError(LookupError):
    pass


class IncidentService:
    def __init__(self, db: Session):
        self.db = db

    def create(self, payload: ComplaintSubmissionCreate) -> ComplaintSubmission:
        incident = ComplaintSubmission(
            name=payload.name,
            identification=payload.identification,
            entered_by_badge=payload.entered_by_badge,
            email=str(payload.email) if payload.email else None,
            phone=payload.phone,
            ai_extracted_data=payload.ai_extracted_data.model_dump(),
            ai_summary_text=payload.ai_summary_text,
            analysis_metadata=payload.analysis_metadata,
            police_input=payload.police_input,
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
        try:
            from app.services.semantic import SemanticIncidentService

            SemanticIncidentService(self.db).process_incident(incident)
            incident.analysis_metadata = {
                **(incident.analysis_metadata or {}),
                "embedding_status": "indexed",
            }
        except Exception as exc:
            logger.warning(
                "Incident persisted without semantic index",
                extra={
                    "feature": "semantic_incidents",
                    "incident_id": incident.id,
                    "error_type": type(exc).__name__,
                },
            )
            incident.analysis_metadata = {
                **(incident.analysis_metadata or {}),
                "embedding_status": "pending",
            }
        self.db.commit()
        self.db.refresh(incident)
        initial_review_reason = (
            incident.review_reason or "Revisión solicitada durante el análisis."
            if incident.requires_human_review
            else None
        )
        try:
            from app.services.reviews import ReviewService

            ReviewService(self.db).assess_incident_if_needed(
                incident,
                initial_quality_reason=initial_review_reason,
            )
        except Exception as exc:
            logger.warning(
                "Incident persisted without administrative assessment",
                extra={
                    "feature": "incident_assessment",
                    "incident_id": incident.id,
                    "error_type": type(exc).__name__,
                },
            )
            incident.analysis_metadata = {
                **(incident.analysis_metadata or {}),
                "administrative_assessment_status": "pending",
            }
            self.db.commit()
            if initial_review_reason:
                self.request_human_review(incident, initial_review_reason)
        return incident

    def request_human_review(
        self,
        incident: ComplaintSubmission,
        reason: str,
    ) -> tuple[HumanReview, bool]:
        from app.services.reviews import ReviewService

        return ReviewService(self.db).request_quality_review(
            incident,
            reason,
            review_type="agent_request",
        )

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
        synthetic_only: bool | None = None,
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
        if synthetic_only is not None:
            condition = (
                ComplaintSubmission.analysis_metadata["synthetic"].as_boolean() == synthetic_only
            )
            query = query.where(condition)
            count_query = count_query.where(condition)
        query = query.order_by(ComplaintSubmission.created_at.desc()).limit(limit).offset(offset)
        return list(self.db.scalars(query)), int(self.db.scalar(count_query) or 0)
