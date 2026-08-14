from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AssistantFeedback, HumanReview
from app.services.incidents import IncidentService


class ReviewNotFoundError(LookupError):
    pass


class ReviewService:
    def __init__(self, db: Session):
        self.db = db

    def list(self, status: str | None = "pending") -> list[HumanReview]:
        query = select(HumanReview).order_by(HumanReview.created_at.desc())
        if status:
            query = query.where(HumanReview.status == status)
        return list(self.db.scalars(query))

    def resolve(self, review_id: int, notes: str) -> HumanReview:
        review = self.db.get(HumanReview, review_id)
        if review is None:
            raise ReviewNotFoundError(review_id)
        review.status = "resolved"
        review.resolution_notes = notes
        review.resolved_at = datetime.now(UTC)
        incident = IncidentService(self.db).get(review.incident_id)
        incident.requires_human_review = False
        incident.status = "reviewed"
        self.db.commit()
        self.db.refresh(review)
        return review

    def record_feedback(
        self,
        *,
        trace_id: str,
        actor_role: str,
        rating: int,
        comment: str | None,
    ) -> AssistantFeedback:
        feedback = AssistantFeedback(
            trace_id=trace_id,
            actor_role=actor_role,
            rating=rating,
            comment=comment,
        )
        self.db.add(feedback)
        self.db.commit()
        self.db.refresh(feedback)
        return feedback
