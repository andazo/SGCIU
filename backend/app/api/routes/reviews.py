from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies import AdminRole
from app.db import get_db
from app.schemas import (
    AssistantFeedbackRequest,
    AssistantFeedbackResponse,
    HumanReviewResponse,
    IncidentHighlightResponse,
    ResolveReviewRequest,
    WorkflowTransitionRequest,
)
from app.services.reviews import HighlightNotFoundError, ReviewNotFoundError, ReviewService

router = APIRouter(prefix="/reviews", tags=["human-review"])
DbSession = Annotated[Session, Depends(get_db)]


@router.get("", response_model=list[HumanReviewResponse])
def list_reviews(
    db: DbSession,
    _actor: AdminRole,
    review_status: Annotated[str | None, Query(alias="status")] = "pending",
):
    return ReviewService(db).list(review_status)


@router.get("/highlights", response_model=list[IncidentHighlightResponse])
def list_highlights(
    db: DbSession,
    _actor: AdminRole,
    highlight_status: Annotated[str | None, Query(alias="status")] = None,
):
    return ReviewService(db).list_highlights(highlight_status)


@router.post(
    "/highlights/{highlight_id}/transition",
    response_model=IncidentHighlightResponse,
)
def transition_highlight(
    highlight_id: int,
    payload: WorkflowTransitionRequest,
    db: DbSession,
    _actor: AdminRole,
):
    if payload.action == "dismiss":
        raise HTTPException(status_code=422, detail="Un resaltado no admite dismissed.")
    try:
        return ReviewService(db).transition_highlight(
            highlight_id,
            payload.action,
            payload.notes,
        )
    except HighlightNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Resaltado no encontrado.") from exc


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


@router.post("/{review_id}/transition", response_model=HumanReviewResponse)
def transition_review(
    review_id: int,
    payload: WorkflowTransitionRequest,
    db: DbSession,
    _actor: AdminRole,
):
    try:
        return ReviewService(db).transition_review(review_id, payload.action, payload.notes)
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
