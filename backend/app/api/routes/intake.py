import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import IntakeSession
from app.schemas import (
    ComplaintSubmissionResponse,
    IntakeMessageRequest,
    IntakeSessionCreateRequest,
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


def require_citizen_session(
    session_id: str,
    db: DbSession,
    x_intake_token: Annotated[str | None, Header()] = None,
):
    session = db.get(IntakeSession, session_id)
    provided = hashlib.sha256((x_intake_token or "").encode()).hexdigest()
    created = session.created_at if session else None
    if created is not None and created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    if (
        session is None
        or created is None
        or created < datetime.now(UTC) - timedelta(hours=24)
        or session.audience != "citizen"
        or not session.access_token_hash
        or not secrets.compare_digest(session.access_token_hash, provided)
    ):
        raise HTTPException(status_code=404, detail="Sesión de intake no encontrada.")


CitizenSession = Annotated[None, Depends(require_citizen_session)]


@router.post("/sessions", response_model=IntakeSessionCreateResponse, status_code=201)
def start_intake(db: DbSession, payload: IntakeSessionCreateRequest | None = None):
    token = secrets.token_urlsafe(32)
    session = IntakeService(db).start(
        registration_mode=payload.registration_mode if payload else "complete",
        access_token=token,
    )
    return IntakeSessionCreateResponse(
        session_id=session.id,
        access_token=token,
        emergency_notice=EMERGENCY_NOTICE,
        assistant_message=INITIAL_MESSAGE,
        prompt_version=session.prompt_version,
        registration_mode=session.registration_mode,
    )


@router.get("/sessions/{session_id}", response_model=IntakeSessionResponse)
def get_intake(session_id: str, db: DbSession, _session: CitizenSession):
    service = IntakeService(db)
    try:
        return service.to_response(service.get(session_id))
    except IntakeSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Sesión de intake no encontrada.") from exc


@router.post("/sessions/{session_id}/messages", response_model=IntakeSessionResponse)
def add_intake_message(
    session_id: str,
    payload: IntakeMessageRequest,
    db: DbSession,
    _session: CitizenSession,
):
    try:
        return IntakeService(db).add_user_message(session_id, payload.content)
    except IntakeSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Sesión de intake no encontrada.") from exc
    except IncompleteIntakeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503, detail="Servicio de IA temporalmente no disponible."
        ) from exc


@router.post(
    "/sessions/{session_id}/submit",
    response_model=ComplaintSubmissionResponse,
    status_code=status.HTTP_201_CREATED,
)
def submit_intake(
    session_id: str,
    payload: IntakeSubmissionRequest,
    db: DbSession,
    _session: CitizenSession,
):
    try:
        return IntakeService(db).submit(session_id, payload)
    except IntakeSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Sesión de intake no encontrada.") from exc
    except IncompleteIntakeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
