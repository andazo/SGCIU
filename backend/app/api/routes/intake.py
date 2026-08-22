from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import (
    ComplaintSubmissionResponse,
    IntakeMessageRequest,
    IntakeSessionCreateResponse,
    IntakeSessionResponse,
    IntakeSubmissionRequest,
)
from app.services.intake import (
    EMERGENCY_NOTICE,
    INITIAL_MESSAGE,
    IncompleteIntakeError,
    IntakeService,
    IntakeSessionNotFoundError,
)

router = APIRouter(prefix="/intake", tags=["intake"])
DbSession = Annotated[Session, Depends(get_db)]


@router.post("/sessions", response_model=IntakeSessionCreateResponse, status_code=201)
def start_intake(db: DbSession):
    session = IntakeService(db).start()
    return IntakeSessionCreateResponse(
        session_id=session.id,
        emergency_notice=EMERGENCY_NOTICE,
        assistant_message=INITIAL_MESSAGE,
        prompt_version=session.prompt_version,
    )


@router.get("/sessions/{session_id}", response_model=IntakeSessionResponse)
def get_intake(session_id: str, db: DbSession):
    service = IntakeService(db)
    try:
        return service.to_response(service.get(session_id))
    except IntakeSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Sesión de intake no encontrada.") from exc


@router.post("/sessions/{session_id}/messages", response_model=IntakeSessionResponse)
def add_intake_message(session_id: str, payload: IntakeMessageRequest, db: DbSession):
    try:
        return IntakeService(db).add_user_message(session_id, payload.content)
    except IntakeSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Sesión de intake no encontrada.") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post(
    "/sessions/{session_id}/submit",
    response_model=ComplaintSubmissionResponse,
    status_code=status.HTTP_201_CREATED,
)
def submit_intake(session_id: str, payload: IntakeSubmissionRequest, db: DbSession):
    try:
        return IntakeService(db).submit(session_id, payload)
    except IntakeSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Sesión de intake no encontrada.") from exc
    except IncompleteIntakeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
