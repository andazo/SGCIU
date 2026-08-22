from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, selectinload

from app.ai.embeddings import EmbeddingProvider, get_embedding_provider
from app.config import Settings, get_settings
from app.models import (
    ComplaintSubmission,
    IncidentCluster,
    IncidentClusterMember,
    IncidentEmbedding,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SimilarIncident:
    incident: ComplaintSubmission
    similarity_score: float
    semantic_score: float
    match_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SemanticRecalculationResult:
    incidents_found: int
    embeddings_updated: int
    embeddings_failed: int
    clusters_rebuilt: int
    cluster_members: int


def _redact_sensitive_text(text: str, people: list[str]) -> str:
    redacted = text
    for person in sorted(people, key=len, reverse=True):
        if person.strip():
            redacted = re.sub(re.escape(person), "[PERSONA]", redacted, flags=re.I)
    redacted = re.sub(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", "[CORREO]", redacted)
    redacted = re.sub(r"(?<!\d)(?:\+?506[ -]?)?\d{4}[ -]?\d{4}(?!\d)", "[TELÉFONO]", redacted)
    return redacted


def canonical_incident_text(incident: ComplaintSubmission) -> str:
    """Build PII-free text used exclusively for semantic comparison."""
    data = incident.ai_extracted_data or {}
    entities = data.get("entities") or {}
    people = entities.get("people", [])
    relevant_entities = [
        *entities.get("vehicles", []),
        *entities.get("objects", []),
        *entities.get("establishments", []),
        *entities.get("landmarks", []),
    ]
    parts = (
        _redact_sensitive_text(data.get("descripcion_detallada") or "", people),
        f"categoría {data.get('categoria_preliminar')}",
        f"distrito {data.get('distrito')}",
        f"ubicación {data.get('direccion_exacta')}",
        f"tipo de lugar {data.get('tipo_lugar')}",
        f"fecha {data.get('fecha_hora_aproximada')}",
        "entidades " + ", ".join(relevant_entities) if relevant_entities else None,
    )
    return ". ".join(str(part).strip() for part in parts if part)


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


class SemanticIncidentService:
    def __init__(
        self,
        db: Session,
        provider: EmbeddingProvider | None = None,
        settings: Settings | None = None,
    ):
        self.db = db
        self.settings = settings or get_settings()
        self.provider = provider or get_embedding_provider(self.settings)

    def index_incident(self, incident: ComplaintSubmission) -> IncidentEmbedding:
        canonical_text = canonical_incident_text(incident)
        vector = self.provider.embed(canonical_text)
        record = self.db.scalar(
            select(IncidentEmbedding).where(IncidentEmbedding.incident_id == incident.id)
        )
        if record is None:
            record = IncidentEmbedding(incident_id=incident.id)
            self.db.add(record)
        record.canonical_text = canonical_text
        record.embedding = vector
        record.embedding_model = self.provider.model_name
        self.db.commit()
        self.db.refresh(record)
        return record

    def find_related(
        self,
        incident: ComplaintSubmission,
        *,
        top_k: int = 5,
        minimum_score: float | None = None,
        candidate_incident_ids: set[int] | None = None,
    ) -> list[SimilarIncident]:
        source_embedding = incident.embedding_record or self.index_incident(incident)
        cutoff = (incident.created_at or datetime.now(UTC)) - timedelta(
            days=self.settings.cluster_time_window_days
        )
        candidate_query = (
            select(IncidentEmbedding)
            .options(selectinload(IncidentEmbedding.incident))
            .join(IncidentEmbedding.incident)
            .where(IncidentEmbedding.incident_id != incident.id)
            .where(ComplaintSubmission.created_at >= cutoff)
        )
        if candidate_incident_ids is not None:
            candidate_query = candidate_query.where(
                IncidentEmbedding.incident_id.in_(candidate_incident_ids)
            )
        candidates = self.db.scalars(candidate_query)
        source_data = incident.ai_extracted_data or {}
        related: list[SimilarIncident] = []
        threshold = minimum_score if minimum_score is not None else 0.0
        for candidate_embedding in candidates:
            candidate = candidate_embedding.incident
            candidate_data = candidate.ai_extracted_data or {}
            semantic_score = cosine_similarity(
                list(source_embedding.embedding), list(candidate_embedding.embedding)
            )
            reasons: list[str] = []
            district_bonus = 0.0
            category_bonus = 0.0
            if source_data.get("distrito") == candidate_data.get("distrito"):
                district_bonus = 0.15
                reasons.append("mismo distrito")
            if source_data.get("categoria_preliminar") == candidate_data.get(
                "categoria_preliminar"
            ):
                category_bonus = 0.10
                reasons.append("misma categoría")
            score = min(1.0, semantic_score * 0.70 + district_bonus + category_bonus + 0.05)
            if semantic_score >= 0.45:
                reasons.insert(0, "descripción semánticamente similar")
            if score >= threshold:
                related.append(
                    SimilarIncident(
                        incident=candidate,
                        similarity_score=round(score, 4),
                        semantic_score=round(semantic_score, 4),
                        match_reasons=tuple(reasons),
                    )
                )
        return sorted(related, key=lambda item: item.similarity_score, reverse=True)[:top_k]

    def update_candidate_cluster(
        self,
        incident: ComplaintSubmission,
        *,
        candidate_incident_ids: set[int] | None = None,
    ) -> IncidentCluster | None:
        related = self.find_related(
            incident,
            top_k=1,
            minimum_score=self.settings.similarity_threshold,
            candidate_incident_ids=candidate_incident_ids,
        )
        if not related:
            return None
        best = related[0]
        membership = self.db.scalar(
            select(IncidentClusterMember).where(
                IncidentClusterMember.incident_id == best.incident.id
            )
        )
        if membership:
            cluster = membership.cluster
        else:
            data = incident.ai_extracted_data or {}
            cluster = IncidentCluster(
                label=(
                    f"{data.get('categoria_preliminar', 'incidentes')} - "
                    f"{data.get('distrito', 'sin distrito')}"
                ),
                explanation="Agrupación candidata creada por similitud híbrida.",
            )
            self.db.add(cluster)
            self.db.flush()
            self.db.add(
                IncidentClusterMember(
                    cluster_id=cluster.id,
                    incident_id=best.incident.id,
                    similarity_score=1.0,
                    match_reason="Incidente de referencia del cluster.",
                )
            )
        existing = self.db.scalar(
            select(IncidentClusterMember).where(
                IncidentClusterMember.cluster_id == cluster.id,
                IncidentClusterMember.incident_id == incident.id,
            )
        )
        if existing is None:
            self.db.add(
                IncidentClusterMember(
                    cluster_id=cluster.id,
                    incident_id=incident.id,
                    similarity_score=best.similarity_score,
                    match_reason=", ".join(best.match_reasons),
                )
            )
        self.db.commit()
        self.db.refresh(cluster)
        return cluster

    def process_incident(self, incident: ComplaintSubmission) -> IncidentCluster | None:
        self.index_incident(incident)
        cluster = self.update_candidate_cluster(incident)
        logger.info(
            "Semantic incident processing completed",
            extra={
                "feature": "semantic_incidents",
                "incident_id": incident.id,
                "cluster_id": cluster.id if cluster else None,
            },
        )
        return cluster

    def list_clusters(self) -> list[IncidentCluster]:
        return list(
            self.db.scalars(
                select(IncidentCluster)
                .options(selectinload(IncidentCluster.members))
                .order_by(IncidentCluster.updated_at.desc())
            )
        )

    def recalculate_all(self) -> SemanticRecalculationResult:
        incidents = list(
            self.db.scalars(
                select(ComplaintSubmission).order_by(
                    ComplaintSubmission.created_at,
                    ComplaintSubmission.id,
                )
            )
        )
        indexed: list[ComplaintSubmission] = []
        failed = 0
        for incident in incidents:
            try:
                self.index_incident(incident)
                incident.analysis_metadata = {
                    **(incident.analysis_metadata or {}),
                    "embedding_status": "indexed",
                }
                self.db.commit()
                indexed.append(incident)
            except Exception as exc:
                failed += 1
                incident.analysis_metadata = {
                    **(incident.analysis_metadata or {}),
                    "embedding_status": "pending",
                }
                self.db.commit()
                logger.warning(
                    "Embedding recalculation failed",
                    extra={
                        "feature": "semantic_recalculation",
                        "incident_id": incident.id,
                        "error_type": type(exc).__name__,
                    },
                )

        if indexed:
            self.db.execute(delete(IncidentClusterMember))
            self.db.execute(delete(IncidentCluster))
            self.db.commit()
            indexed_ids = {incident.id for incident in indexed}
            for incident in indexed:
                self.update_candidate_cluster(
                    incident,
                    candidate_incident_ids=indexed_ids,
                )

        cluster_count = int(self.db.scalar(select(func.count(IncidentCluster.id))) or 0)
        member_count = int(self.db.scalar(select(func.count(IncidentClusterMember.id))) or 0)
        return SemanticRecalculationResult(
            incidents_found=len(incidents),
            embeddings_updated=len(indexed),
            embeddings_failed=failed,
            clusters_rebuilt=cluster_count,
            cluster_members=member_count,
        )
