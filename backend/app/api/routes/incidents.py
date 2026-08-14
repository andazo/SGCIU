from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import (
    ComplaintSubmissionCreate,
    ComplaintSubmissionResponse,
    IncidentListResponse,
)
from app.services.incidents import IncidentNotFoundError, IncidentService

router = APIRouter(prefix="/incidents", tags=["incidents"])
DbSession = Annotated[Session, Depends(get_db)]


@router.post("", response_model=ComplaintSubmissionResponse, status_code=status.HTTP_201_CREATED)
def create_incident(payload: ComplaintSubmissionCreate, db: DbSession):
    return IncidentService(db).create(payload)


@router.get("", response_model=IncidentListResponse)
def list_incidents(
    db: DbSession,
    district: str | None = None,
    category: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    items, total = IncidentService(db).list(
        district=district, category=category, limit=limit, offset=offset
    )
    return IncidentListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/{incident_id}", response_model=ComplaintSubmissionResponse)
def get_incident(incident_id: int, db: DbSession):
    try:
        return IncidentService(db).get(incident_id)
    except IncidentNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Incidente no encontrado.") from exc
