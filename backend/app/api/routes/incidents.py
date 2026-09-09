from datetime import UTC, datetime, timedelta
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
    RecurrentPatternMemberResponse,
    RecurrentPatternResponse,
    RelatedIncident,
    RelatedIncidentList,
    SemanticRecalculationResponse,
)
from app.services.incidents import IncidentNotFoundError, IncidentService
from app.services.semantic import SemanticIncidentService, incident_time_reference

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


@router.get("/{incident_id:int}", response_model=ComplaintSubmissionResponse)
def get_incident(incident_id: int, db: DbSession, _actor: AdminRole):
    try:
        return IncidentService(db).get(incident_id)
    except IncidentNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Incidente no encontrado.") from exc


@router.get("/{incident_id:int}/related", response_model=RelatedIncidentList)
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
                occurred_at=incident_time_reference(item.incident).value,
                temporal_basis=incident_time_reference(item.incident).basis,
            )
            for item in items
        ],
    )


@router.post("/{incident_id:int}/semantic-index", status_code=status.HTTP_204_NO_CONTENT)
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


@router.get("/clusters/recurrent", response_model=list[RecurrentPatternResponse])
def list_recurrent_patterns(
    db: DbSession,
    _actor: AdminRole,
    window_days: Annotated[int, Query(ge=1, le=365)] = 30,
):
    cutoff_service = SemanticIncidentService(db)
    patterns = []
    for cluster in cutoff_service.list_recurrent_patterns(window_days=window_days):
        threshold = datetime.now(UTC) - timedelta(days=window_days)
        members = sorted(
            [
                member
                for member in cluster.members
                if member.incident and incident_time_reference(member.incident).value >= threshold
            ],
            key=lambda member: incident_time_reference(member.incident).value,
        )
        incidents = [member.incident for member in members]
        data = [incident.ai_extracted_data or {} for incident in incidents]
        districts = [item.get("distrito") for item in data if item.get("distrito")]
        categories = [
            item.get("categoria_preliminar") for item in data if item.get("categoria_preliminar")
        ]
        signals = sorted(
            {
                reason.strip()
                for member in members
                for reason in member.match_reason.split(",")
                if reason.strip()
            }
        )
        patterns.append(
            RecurrentPatternResponse(
                id=cluster.id,
                title=cluster.label,
                incident_count=len(members),
                first_seen=incident_time_reference(members[0].incident).value,
                last_seen=incident_time_reference(members[-1].incident).value,
                district=max(set(districts), key=districts.count) if districts else None,
                category=max(set(categories), key=categories.count) if categories else None,
                average_similarity=round(
                    sum(member.similarity_score for member in members) / len(members), 4
                ),
                signals=signals,
                members=[
                    RecurrentPatternMemberResponse(
                        incident_id=member.incident_id,
                        created_at=member.incident.created_at,
                        occurred_at=incident_time_reference(member.incident).value,
                        temporal_basis=incident_time_reference(member.incident).basis,
                        category=(member.incident.ai_extracted_data or {}).get(
                            "categoria_preliminar"
                        ),
                        district=(member.incident.ai_extracted_data or {}).get("distrito"),
                        address=(member.incident.ai_extracted_data or {}).get("direccion_exacta"),
                        similarity_score=member.similarity_score,
                        match_reason=member.match_reason,
                    )
                    for member in members
                ],
            )
        )
    return patterns


@router.post("/clusters/recalculate", response_model=SemanticRecalculationResponse)
def recalculate_semantic_index(db: DbSession, _actor: AdminRole):
    result = SemanticIncidentService(db).recalculate_all()
    return SemanticRecalculationResponse(
        incidents_found=result.incidents_found,
        embeddings_updated=result.embeddings_updated,
        embeddings_failed=result.embeddings_failed,
        clusters_rebuilt=result.clusters_rebuilt,
        cluster_members=result.cluster_members,
    )
