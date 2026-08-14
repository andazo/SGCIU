from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import ComplaintSubmission, IncidentCluster
from app.services.incidents import IncidentNotFoundError, IncidentService
from app.services.semantic import SemanticIncidentService
from app.tools.registry import ToolDefinition, ToolRegistry


class ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GetIncidentInput(ToolInput):
    incident_id: int = Field(ge=1)


class SearchIncidentsInput(ToolInput):
    district: str | None = None
    category: str | None = None
    limit: int = Field(default=20, ge=1, le=100)


class AggregateIncidentsInput(ToolInput):
    group_by: Literal["categoria_preliminar", "distrito"]
    district: str | None = None
    category: str | None = None


class FindRelatedInput(ToolInput):
    incident_id: int = Field(ge=1)
    top_k: int = Field(default=5, ge=1, le=20)


class GetClusterInput(ToolInput):
    cluster_id: int = Field(ge=1)


class RequestReviewInput(ToolInput):
    incident_id: int = Field(ge=1)
    reason: str = Field(min_length=10, max_length=500)


def _safe_incident(incident: ComplaintSubmission) -> dict[str, object]:
    data = incident.ai_extracted_data or {}
    return {
        "incident_id": incident.id,
        "created_at": incident.created_at.isoformat() if incident.created_at else None,
        "status": incident.status,
        "category": data.get("categoria_preliminar"),
        "district": data.get("distrito"),
        "address": data.get("direccion_exacta"),
        "place_type": data.get("tipo_lugar"),
        "event_datetime": data.get("fecha_hora_aproximada"),
        "summary": incident.ai_summary_text,
        "requires_human_review": incident.requires_human_review,
    }


def get_incident(db: Session, arguments: GetIncidentInput) -> dict[str, object]:
    try:
        incident = IncidentService(db).get(arguments.incident_id)
    except IncidentNotFoundError:
        return {"found": False, "incident_id": arguments.incident_id}
    return {"found": True, "incident": _safe_incident(incident)}


def search_incidents(db: Session, arguments: SearchIncidentsInput) -> dict[str, object]:
    incidents, total = IncidentService(db).list(
        district=arguments.district,
        category=arguments.category,
        limit=arguments.limit,
    )
    return {
        "total": total,
        "returned": len(incidents),
        "incidents": [_safe_incident(incident) for incident in incidents],
    }


def aggregate_incidents(db: Session, arguments: AggregateIncidentsInput) -> dict[str, object]:
    group_expression = ComplaintSubmission.ai_extracted_data[arguments.group_by].as_string()
    query = select(group_expression, func.count()).group_by(group_expression)
    if arguments.district:
        query = query.where(
            ComplaintSubmission.ai_extracted_data["distrito"].as_string() == arguments.district
        )
    if arguments.category:
        query = query.where(
            ComplaintSubmission.ai_extracted_data["categoria_preliminar"].as_string()
            == arguments.category
        )
    rows = db.execute(query.order_by(func.count().desc())).all()
    return {
        "group_by": arguments.group_by,
        "filters": {"district": arguments.district, "category": arguments.category},
        "groups": [{"value": value or "sin_clasificar", "count": count} for value, count in rows],
        "total": sum(count for _, count in rows),
    }


def find_related_incidents(db: Session, arguments: FindRelatedInput) -> dict[str, object]:
    try:
        incident = IncidentService(db).get(arguments.incident_id)
    except IncidentNotFoundError:
        return {"found": False, "incident_id": arguments.incident_id, "related": []}
    related = SemanticIncidentService(db).find_related(incident, top_k=arguments.top_k)
    return {
        "found": True,
        "incident_id": incident.id,
        "related": [
            {
                **_safe_incident(item.incident),
                "similarity_score": item.similarity_score,
                "semantic_score": item.semantic_score,
                "match_reasons": list(item.match_reasons),
            }
            for item in related
        ],
    }


def get_incident_cluster(db: Session, arguments: GetClusterInput) -> dict[str, object]:
    cluster = db.scalar(
        select(IncidentCluster)
        .options(selectinload(IncidentCluster.members))
        .where(IncidentCluster.id == arguments.cluster_id)
    )
    if cluster is None:
        return {"found": False, "cluster_id": arguments.cluster_id}
    return {
        "found": True,
        "cluster": {
            "cluster_id": cluster.id,
            "label": cluster.label,
            "status": cluster.status,
            "explanation": cluster.explanation,
            "members": [
                {
                    "incident_id": member.incident_id,
                    "similarity_score": member.similarity_score,
                    "match_reason": member.match_reason,
                }
                for member in cluster.members
            ],
        },
    }


def request_human_review(db: Session, arguments: RequestReviewInput) -> dict[str, object]:
    try:
        incident = IncidentService(db).get(arguments.incident_id)
    except IncidentNotFoundError:
        return {"created": False, "incident_id": arguments.incident_id}
    review, created = IncidentService(db).request_human_review(incident, arguments.reason)
    return {"created": created, "review_id": review.id, "incident_id": incident.id}


def build_incident_tool_registry() -> ToolRegistry:
    return ToolRegistry(
        [
            ToolDefinition(
                name="get_incident",
                description="Obtiene los datos operativos sanitizados de un incidente por ID.",
                input_model=GetIncidentInput,
                handler=get_incident,
            ),
            ToolDefinition(
                name="search_incidents",
                description=(
                    "Busca incidentes aplicando filtros opcionales de distrito y categoría."
                ),
                input_model=SearchIncidentsInput,
                handler=search_incidents,
            ),
            ToolDefinition(
                name="aggregate_incidents",
                description="Cuenta incidentes agrupados por categoría o distrito usando SQL.",
                input_model=AggregateIncidentsInput,
                handler=aggregate_incidents,
            ),
            ToolDefinition(
                name="find_related_incidents",
                description="Busca incidentes relacionados mediante similitud híbrida.",
                input_model=FindRelatedInput,
                handler=find_related_incidents,
            ),
            ToolDefinition(
                name="get_incident_cluster",
                description="Consulta un cluster candidato y sus incidentes miembros.",
                input_model=GetClusterInput,
                handler=get_incident_cluster,
            ),
            ToolDefinition(
                name="request_human_review",
                description="Crea una solicitud explícita de revisión humana para un incidente.",
                input_model=RequestReviewInput,
                handler=request_human_review,
                mutating=True,
            ),
        ]
    )
