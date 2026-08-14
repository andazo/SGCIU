from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies import AdminRole
from app.db import get_db
from app.schemas import (
    ClusterMemberResponse,
    ComplaintSubmissionCreate,
    ComplaintSubmissionResponse,
    IncidentClusterResponse,
    IncidentListResponse,
    RelatedIncident,
    RelatedIncidentList,
)
from app.services.incidents import IncidentNotFoundError, IncidentService
from app.services.semantic import SemanticIncidentService

router = APIRouter(prefix="/incidents", tags=["incidents"])
DbSession = Annotated[Session, Depends(get_db)]


@router.post("", response_model=ComplaintSubmissionResponse, status_code=status.HTTP_201_CREATED)
def create_incident(payload: ComplaintSubmissionCreate, db: DbSession, _actor: AdminRole):
    return IncidentService(db).create(payload)


@router.get("", response_model=IncidentListResponse)
def list_incidents(
    db: DbSession,
    _actor: AdminRole,
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
def get_incident(incident_id: int, db: DbSession, _actor: AdminRole):
    try:
        return IncidentService(db).get(incident_id)
    except IncidentNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Incidente no encontrado.") from exc


@router.get("/{incident_id}/related", response_model=RelatedIncidentList)
def get_related_incidents(
    incident_id: int,
    db: DbSession,
    _actor: AdminRole,
    top_k: Annotated[int, Query(ge=1, le=20)] = 5,
):
    try:
        incident = IncidentService(db).get(incident_id)
    except IncidentNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Incidente no encontrado.") from exc
    items = SemanticIncidentService(db).find_related(incident, top_k=top_k)
    return RelatedIncidentList(
        source_incident_id=incident_id,
        items=[
            RelatedIncident(
                incident_id=item.incident.id,
                category=item.incident.ai_extracted_data.get("categoria_preliminar"),
                district=item.incident.ai_extracted_data.get("distrito"),
                address=item.incident.ai_extracted_data.get("direccion_exacta"),
                similarity_score=item.similarity_score,
                semantic_score=item.semantic_score,
                match_reasons=list(item.match_reasons),
            )
            for item in items
        ],
    )


@router.post("/{incident_id}/semantic-index", status_code=status.HTTP_204_NO_CONTENT)
def reindex_incident(incident_id: int, db: DbSession, _actor: AdminRole):
    try:
        incident = IncidentService(db).get(incident_id)
    except IncidentNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Incidente no encontrado.") from exc
    SemanticIncidentService(db).process_incident(incident)


@router.get("/clusters/candidates", response_model=list[IncidentClusterResponse])
def list_candidate_clusters(db: DbSession, _actor: AdminRole):
    return [
        IncidentClusterResponse(
            id=cluster.id,
            label=cluster.label,
            status=cluster.status,
            explanation=cluster.explanation,
            members=[
                ClusterMemberResponse(
                    incident_id=member.incident_id,
                    similarity_score=member.similarity_score,
                    match_reason=member.match_reason,
                )
                for member in cluster.members
            ],
        )
        for cluster in SemanticIncidentService(db).list_clusters()
    ]
