from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies import AdminRole
from app.db import get_db
from app.schemas import (
    AssistantFeedbackRequest,
    AssistantFeedbackResponse,
    HumanReviewResponse,
    ResolveReviewRequest,
)
from app.services.reviews import ReviewNotFoundError, ReviewService

router = APIRouter(prefix="/reviews", tags=["human-review"])
DbSession = Annotated[Session, Depends(get_db)]


@router.get("", response_model=list[HumanReviewResponse])
def list_reviews(
    db: DbSession,
    _actor: AdminRole,
    review_status: Annotated[str | None, Query(alias="status")] = "pending",
):
    return ReviewService(db).list(review_status)


@router.post("/{review_id}/resolve", response_model=HumanReviewResponse)
def resolve_review(
    review_id: int,
    payload: ResolveReviewRequest,
    db: DbSession,
    _actor: AdminRole,
):
    try:
        return ReviewService(db).resolve(review_id, payload.notes)
    except ReviewNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Revisión no encontrada.") from exc


@router.post(
    "/feedback",
    response_model=AssistantFeedbackResponse,
    status_code=status.HTTP_201_CREATED,
)
def record_feedback(
    payload: AssistantFeedbackRequest,
    db: DbSession,
    _actor: AdminRole,
):
    return ReviewService(db).record_feedback(
        trace_id=payload.trace_id,
        actor_role="admin",
        rating=payload.rating,
        comment=payload.comment,
    )
