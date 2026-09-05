from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import ComplaintSubmission, IncidentCluster
from app.services.incidents import IncidentNotFoundError, IncidentService
from app.services.normalization import canonical_category, canonical_district, filter_values
from app.services.semantic import SemanticIncidentService, _is_recent
from app.tools.legal import legal_tool_definitions
from app.tools.registry import ToolDefinition, ToolRegistry


class ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GetIncidentInput(ToolInput):
    incident_id: int = Field(ge=1)


class DateRangeInput(ToolInput):
    created_from: date | None = None
    created_to: date | None = None

    @model_validator(mode="after")
    def validate_date_range(self):
        if self.created_from and self.created_to and self.created_from > self.created_to:
            raise ValueError("created_from no puede ser posterior a created_to.")
        return self


class SearchIncidentsInput(DateRangeInput):
    district: str | None = None
    category: str | None = None
    synthetic_only: bool | None = None
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=10_000)


class AggregateIncidentsInput(DateRangeInput):
    group_by: Literal["categoria_preliminar", "distrito"]
    district: str | None = None
    category: str | None = None
    synthetic_only: bool | None = None


class FindRelatedInput(ToolInput):
    incident_id: int = Field(ge=1)
    top_k: int = Field(default=5, ge=1, le=20)


class GetClusterInput(ToolInput):
    cluster_id: int = Field(ge=1)


class GetRecurrentPatternsInput(ToolInput):
    window_days: int = Field(default=30, ge=1, le=365)


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
        "source": "police" if incident.police_input else "citizen",
        "synthetic": bool((incident.analysis_metadata or {}).get("synthetic")),
        "synthetic_case_id": (incident.analysis_metadata or {}).get("synthetic_case_id"),
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
        synthetic_only=arguments.synthetic_only,
        created_from=arguments.created_from,
        created_to=arguments.created_to,
        limit=arguments.limit,
        offset=arguments.offset,
    )
    return {
        "total": total,
        "returned": len(incidents),
        "offset": arguments.offset,
        "limit": arguments.limit,
        "has_more": arguments.offset + len(incidents) < total,
        "filters": {
            "district": canonical_district(arguments.district),
            "category": canonical_category(arguments.category),
            "synthetic_only": arguments.synthetic_only,
            "created_from": arguments.created_from.isoformat() if arguments.created_from else None,
            "created_to": arguments.created_to.isoformat() if arguments.created_to else None,
        },
        "incidents": [_safe_incident(incident) for incident in incidents],
    }


def aggregate_incidents(db: Session, arguments: AggregateIncidentsInput) -> dict[str, object]:
    group_expression = ComplaintSubmission.ai_extracted_data[arguments.group_by].as_string()
    query = select(group_expression, func.count()).group_by(group_expression)
    normalized_district = canonical_district(arguments.district)
    normalized_category = canonical_category(arguments.category)
    if normalized_district:
        district_values = filter_values(normalized_district, kind="district") or (
            normalized_district,
        )
        query = query.where(
            ComplaintSubmission.ai_extracted_data["distrito"].as_string().in_(district_values)
        )
    if normalized_category:
        category_values = filter_values(normalized_category, kind="category") or (
            normalized_category,
        )
        query = query.where(
            ComplaintSubmission.ai_extracted_data["categoria_preliminar"].as_string().in_(category_values)
        )
    if arguments.synthetic_only is not None:
        query = query.where(
            ComplaintSubmission.analysis_metadata["synthetic"].as_boolean()
            == arguments.synthetic_only
        )
    if arguments.created_from:
        query = query.where(
            ComplaintSubmission.created_at
            >= datetime.combine(arguments.created_from, time.min, tzinfo=UTC)
        )
    if arguments.created_to:
        query = query.where(
            ComplaintSubmission.created_at
            < datetime.combine(arguments.created_to + timedelta(days=1), time.min, tzinfo=UTC)
        )
    rows = db.execute(query.order_by(func.count().desc())).all()
    groups: dict[str, int] = {}
    for value, count in rows:
        if arguments.group_by == "distrito":
            key = canonical_district(value) or "sin_clasificar"
        else:
            key = canonical_category(value) or "sin_clasificar"
        groups[key] = groups.get(key, 0) + count
    return {
        "group_by": arguments.group_by,
        "filters": {
            "district": normalized_district,
            "category": normalized_category,
            "synthetic_only": arguments.synthetic_only,
            "created_from": arguments.created_from.isoformat() if arguments.created_from else None,
            "created_to": arguments.created_to.isoformat() if arguments.created_to else None,
        },
        "groups": [
            {"value": value, "count": count}
            for value, count in sorted(groups.items(), key=lambda item: item[1], reverse=True)
        ],
        "total": sum(groups.values()),
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


def get_recurrent_patterns(
    db: Session, arguments: GetRecurrentPatternsInput
) -> dict[str, object]:
    service = SemanticIncidentService(db)
    window_days = arguments.window_days
    threshold = datetime.now(UTC) - timedelta(days=window_days)
    patterns: list[dict[str, object]] = []
    for cluster in service.list_recurrent_patterns():
        members = [
            member
            for member in cluster.members
            if member.incident and _is_recent(member.incident.created_at, threshold)
        ]
        if not members:
            continue
        patterns.append(
            {
                "pattern_id": cluster.id,
                "label": cluster.label,
                "incident_count": len(members),
                "average_similarity": round(
                    sum(member.similarity_score for member in members) / len(members), 4
                ),
                "members": [
                    {
                        "incident_id": member.incident_id,
                        "created_at": member.incident.created_at.isoformat()
                        if member.incident.created_at
                        else None,
                        "category": (member.incident.ai_extracted_data or {}).get(
                            "categoria_preliminar"
                        ),
                        "district": (member.incident.ai_extracted_data or {}).get("distrito"),
                        "address": (member.incident.ai_extracted_data or {}).get(
                            "direccion_exacta"
                        ),
                        "similarity_score": member.similarity_score,
                        "match_reason": member.match_reason,
                    }
                    for member in sorted(
                        members,
                        key=lambda item: item.incident.created_at,
                    )
                ],
            }
        )
    return {
        "window_days": window_days,
        "minimum_incidents": 3,
        "patterns": patterns,
        "total_patterns": len(patterns),
    }


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
                    "Busca incidentes por distrito, categoría y origen sintético opcional."
                ),
                input_model=SearchIncidentsInput,
                handler=search_incidents,
            ),
            ToolDefinition(
                name="aggregate_incidents",
                description=(
                    "Cuenta incidentes por categoría o distrito y permite aislar datos "
                    "sintéticos con synthetic_only."
                ),
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
                name="get_recurrent_patterns",
                description=(
                    "Obtiene patrones recurrentes proactivos con al menos tres incidentes "
                    "similares dentro de la ventana temporal configurada."
                ),
                input_model=GetRecurrentPatternsInput,
                handler=get_recurrent_patterns,
            ),
            *legal_tool_definitions(),
        ]
    )
