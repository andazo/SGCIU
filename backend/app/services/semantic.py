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


@dataclass(frozen=True, slots=True)
class IncidentTimeReference:
    value: datetime
    basis: str
    precision: str


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
        f"recurrencia {data.get('recurrence_pattern')}" if data.get("is_recurring") else None,
        "entidades " + ", ".join(relevant_entities) if relevant_entities else None,
    )
    return ". ".join(str(part).strip() for part in parts if part)


def canonical_location_text(incident: ComplaintSubmission) -> str:
    """Build the location-only text used by recurrent-pattern scoring."""
    data = incident.ai_extracted_data or {}
    entities = data.get("entities") or {}
    landmarks = entities.get("landmarks", [])
    establishments = entities.get("establishments", [])
    parts = (
        f"distrito {data.get('distrito')}",
        f"dirección {data.get('direccion_exacta')}",
        f"tipo de lugar {data.get('tipo_lugar')}",
        "referencias " + ", ".join([*landmarks, *establishments])
        if landmarks or establishments
        else None,
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


def _is_recent(created_at: datetime | None, cutoff: datetime) -> bool:
    if created_at is None:
        return False
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    return created_at >= cutoff


def _aware_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def incident_time_reference(incident: ComplaintSubmission) -> IncidentTimeReference:
    """Prefer the event time and retain an explicit, auditable registration fallback."""
    if incident.occurred_at is not None:
        return IncidentTimeReference(
            value=_aware_utc(incident.occurred_at),
            basis="occurred_at",
            precision=incident.occurred_at_precision or "unknown",
        )
    raw = (incident.ai_extracted_data or {}).get("incident_datetime")
    if isinstance(raw, str) and raw:
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            parsed = None
        if parsed is not None:
            return IncidentTimeReference(
                value=_aware_utc(parsed),
                basis="incident_datetime_json",
                precision=str(
                    (incident.ai_extracted_data or {}).get("incident_datetime_precision", "unknown")
                ),
            )
    registered = incident.created_at or datetime.now(UTC)
    return IncidentTimeReference(
        value=_aware_utc(registered),
        basis="created_at_fallback",
        precision="unknown",
    )


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
        vectors = self.provider.embed_many([canonical_text, canonical_location_text(incident)])
        record = self.db.scalar(
            select(IncidentEmbedding).where(IncidentEmbedding.incident_id == incident.id)
        )
        if record is None:
            record = IncidentEmbedding(incident_id=incident.id)
            self.db.add(record)
        record.canonical_text = canonical_text
        record.embedding = vectors[0]
        record.location_embedding = vectors[1]
        record.embedding_model = self.provider.model_name
        self.db.commit()
        self.db.refresh(record)
        return record

    def find_related(
        self,
        incident: ComplaintSubmission,
        *,
        top_k: int | None = 5,
        minimum_score: float | None = None,
        candidate_incident_ids: set[int] | None = None,
    ) -> list[SimilarIncident]:
        source_embedding = incident.embedding_record or self.index_incident(incident)
        time_reference = incident_time_reference(incident)
        lower_bound = time_reference.value - timedelta(days=self.settings.cluster_time_window_days)
        upper_bound = time_reference.value + timedelta(days=self.settings.cluster_time_window_days)
        candidate_time = func.coalesce(
            ComplaintSubmission.occurred_at,
            ComplaintSubmission.created_at,
        )
        base_candidate_query = (
            select(IncidentEmbedding)
            .options(selectinload(IncidentEmbedding.incident))
            .join(IncidentEmbedding.incident)
            .where(IncidentEmbedding.incident_id != incident.id)
            .where(candidate_time >= lower_bound)
            .where(candidate_time <= upper_bound)
        )
        if candidate_incident_ids is not None:
            base_candidate_query = base_candidate_query.where(
                IncidentEmbedding.incident_id.in_(candidate_incident_ids)
            )
        candidates = self._candidate_embeddings(
            base_candidate_query,
            source_embedding,
            lower_bound=lower_bound,
            upper_bound=upper_bound,
            candidate_incident_ids=candidate_incident_ids,
        )
        source_data = incident.ai_extracted_data or {}
        related: list[SimilarIncident] = []
        threshold = minimum_score if minimum_score is not None else 0.0
        for candidate_embedding in candidates:
            candidate = candidate_embedding.incident
            candidate_reference = incident_time_reference(candidate)
            if abs((candidate_reference.value - time_reference.value).total_seconds()) > (
                self.settings.cluster_time_window_days * 86_400
            ):
                continue
            candidate_data = candidate.ai_extracted_data or {}
            semantic_score = cosine_similarity(
                list(source_embedding.embedding), list(candidate_embedding.embedding)
            )
            location_score = cosine_similarity(
                list(source_embedding.location_embedding or []),
                list(candidate_embedding.location_embedding or []),
            )
            reasons: list[str] = []
            district_bonus = 0.0
            category_bonus = 0.0
            if source_data.get("distrito") == candidate_data.get("distrito"):
                district_bonus = 0.10
                reasons.append("mismo distrito")
            if source_data.get("categoria_preliminar") == candidate_data.get(
                "categoria_preliminar"
            ):
                category_bonus = 0.08
                reasons.append("misma categoría")
            if location_score >= 0.60:
                reasons.insert(0, "ubicación semánticamente similar")
            score = min(
                1.0,
                semantic_score * 0.52
                + location_score * 0.28
                + district_bonus
                + category_bonus
                + 0.02,
            )
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
        ranked = sorted(related, key=lambda item: item.similarity_score, reverse=True)
        return ranked[:top_k] if top_k is not None else ranked

    def _candidate_embeddings(
        self,
        base_query,
        source_embedding: IncidentEmbedding,
        *,
        lower_bound: datetime,
        upper_bound: datetime,
        candidate_incident_ids: set[int] | None,
    ) -> list[IncidentEmbedding]:
        if self.db.bind is None or self.db.bind.dialect.name != "postgresql":
            return list(self.db.scalars(base_query))
        candidate_limit = self.settings.cluster_candidate_k
        if candidate_incident_ids is not None:
            candidate_limit = min(candidate_limit, max(1, len(candidate_incident_ids)))
        candidate_time = func.coalesce(
            ComplaintSubmission.occurred_at,
            ComplaintSubmission.created_at,
        )
        common_filters = (
            IncidentEmbedding.incident_id != source_embedding.incident_id,
            candidate_time >= lower_bound,
            candidate_time <= upper_bound,
        )
        if candidate_incident_ids is not None:
            common_filters += (
                IncidentEmbedding.incident_id.in_(candidate_incident_ids),
            )
        semantic_distance = IncidentEmbedding.embedding.cosine_distance(
            list(source_embedding.embedding)
        )
        semantic_ids = set(
            self.db.scalars(
                select(IncidentEmbedding.incident_id)
                .join(IncidentEmbedding.incident)
                .where(*common_filters)
                .order_by(semantic_distance)
                .limit(candidate_limit)
            )
        )
        location_ids: set[int] = set()
        if source_embedding.location_embedding is not None:
            location_distance = IncidentEmbedding.location_embedding.cosine_distance(
                list(source_embedding.location_embedding)
            )
            location_ids = set(
                self.db.scalars(
                    select(IncidentEmbedding.incident_id)
                    .join(IncidentEmbedding.incident)
                    .where(*common_filters)
                    .where(IncidentEmbedding.location_embedding.is_not(None))
                    .order_by(location_distance)
                    .limit(candidate_limit)
                )
            )
        shortlisted_ids = semantic_ids | location_ids
        if not shortlisted_ids:
            return []
        return list(
            self.db.scalars(
                select(IncidentEmbedding)
                .options(selectinload(IncidentEmbedding.incident))
                .where(IncidentEmbedding.incident_id.in_(shortlisted_ids))
            )
        )

    def update_candidate_cluster(
        self,
        incident: ComplaintSubmission,
        *,
        candidate_incident_ids: set[int] | None = None,
    ) -> IncidentCluster | None:
        related = self.find_related(
            incident,
            top_k=None,
            minimum_score=self.settings.similarity_threshold,
            candidate_incident_ids=candidate_incident_ids,
        )
        if not related:
            self._detach_from_candidate_clusters(incident.id)
            return None
        related_ids = {item.incident.id for item in related}
        memberships = list(
            self.db.scalars(
                select(IncidentClusterMember)
                .options(selectinload(IncidentClusterMember.cluster))
                .where(IncidentClusterMember.incident_id.in_(related_ids))
            )
        )
        clusters = {membership.cluster.id: membership.cluster for membership in memberships}
        if clusters:
            cluster = clusters[min(clusters)]
            merged_cluster_ids = set(clusters) - {cluster.id}
            if merged_cluster_ids:
                existing_member_ids = {
                    member_id
                    for member_id in self.db.scalars(
                        select(IncidentClusterMember.incident_id).where(
                            IncidentClusterMember.cluster_id == cluster.id
                        )
                    )
                }
                merge_members = list(
                    self.db.scalars(
                        select(IncidentClusterMember).where(
                            IncidentClusterMember.cluster_id.in_(merged_cluster_ids)
                        )
                    )
                )
                for member in merge_members:
                    if member.incident_id in existing_member_ids:
                        self.db.delete(member)
                    else:
                        member.cluster_id = cluster.id
                        existing_member_ids.add(member.incident_id)
                self.db.flush()
                self.db.execute(
                    delete(IncidentCluster).where(IncidentCluster.id.in_(merged_cluster_ids))
                )
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
        best_by_id = {item.incident.id: item for item in related}
        member_ids = {incident.id, *related_ids}
        existing_memberships = list(
            self.db.scalars(
                select(IncidentClusterMember).where(
                    IncidentClusterMember.incident_id.in_(member_ids)
                )
            )
        )
        existing_in_target = {
            member.incident_id for member in existing_memberships if member.cluster_id == cluster.id
        }
        for member in existing_memberships:
            if member.cluster_id != cluster.id:
                self.db.delete(member)
        for member_id in member_ids - existing_in_target:
            match = best_by_id.get(member_id)
            self.db.add(
                IncidentClusterMember(
                    cluster_id=cluster.id,
                    incident_id=member_id,
                    similarity_score=match.similarity_score if match else 1.0,
                    match_reason=(
                        ", ".join(match.match_reasons)
                        if match
                        else "Incidente de referencia del cluster."
                    ),
                )
            )
        self.db.commit()
        self.db.refresh(cluster)
        return cluster

    def _detach_from_candidate_clusters(self, incident_id: int) -> None:
        memberships = list(
            self.db.scalars(
                select(IncidentClusterMember).where(
                    IncidentClusterMember.incident_id == incident_id
                )
            )
        )
        if not memberships:
            return
        affected_cluster_ids = {membership.cluster_id for membership in memberships}
        for membership in memberships:
            self.db.delete(membership)
        self.db.flush()
        for cluster_id in affected_cluster_ids:
            remaining = int(
                self.db.scalar(
                    select(func.count(IncidentClusterMember.id)).where(
                        IncidentClusterMember.cluster_id == cluster_id
                    )
                )
                or 0
            )
            if remaining < 2:
                self.db.execute(
                    delete(IncidentClusterMember).where(
                        IncidentClusterMember.cluster_id == cluster_id
                    )
                )
                self.db.execute(delete(IncidentCluster).where(IncidentCluster.id == cluster_id))
        self.db.commit()

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

    def list_recurrent_patterns(
        self,
        *,
        minimum_incidents: int = 3,
        window_days: int | None = None,
        reference: datetime | None = None,
    ) -> list[IncidentCluster]:
        """Return proactive patterns with at least N recent incident members."""
        effective_window = window_days or self.settings.cluster_time_window_days
        cutoff = (reference or datetime.now(UTC)) - timedelta(days=effective_window)
        recurrent: list[IncidentCluster] = []
        for cluster in self.list_clusters():
            recent_count = sum(
                1
                for member in cluster.members
                if member.incident and incident_time_reference(member.incident).value >= cutoff
            )
            if recent_count >= minimum_incidents:
                recurrent.append(cluster)
        return recurrent

    def recalculate_all(self) -> SemanticRecalculationResult:
        incidents = list(
            self.db.scalars(
                select(ComplaintSubmission).order_by(
                    func.coalesce(
                        ComplaintSubmission.occurred_at,
                        ComplaintSubmission.created_at,
                    ),
                    ComplaintSubmission.id,
                )
            )
        )
        indexed: list[ComplaintSubmission] = []
        failed = 0
        for incident in incidents:
            try:
                reference = incident_time_reference(incident)
                if reference.basis == "incident_datetime_json":
                    incident.occurred_at = reference.value
                    incident.occurred_at_precision = reference.precision
                    incident.occurred_at_source = "explicit"
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
            self.rebuild_clusters(indexed)

        cluster_count = int(self.db.scalar(select(func.count(IncidentCluster.id))) or 0)
        member_count = int(self.db.scalar(select(func.count(IncidentClusterMember.id))) or 0)
        return SemanticRecalculationResult(
            incidents_found=len(incidents),
            embeddings_updated=len(indexed),
            embeddings_failed=failed,
            clusters_rebuilt=cluster_count,
            cluster_members=member_count,
        )

    def rebuild_clusters(
        self,
        incidents: list[ComplaintSubmission] | None = None,
    ) -> tuple[int, int]:
        """Rebuild deterministic connected candidate groups without new embeddings."""
        candidates = incidents or list(
            self.db.scalars(
                select(ComplaintSubmission)
                .join(IncidentEmbedding, IncidentEmbedding.incident_id == ComplaintSubmission.id)
                .order_by(
                    func.coalesce(
                        ComplaintSubmission.occurred_at,
                        ComplaintSubmission.created_at,
                    ),
                    ComplaintSubmission.id,
                )
            )
        )
        self.db.execute(delete(IncidentClusterMember))
        self.db.execute(delete(IncidentCluster))
        self.db.commit()
        candidate_ids = {incident.id for incident in candidates}
        for incident in candidates:
            self.update_candidate_cluster(
                incident,
                candidate_incident_ids=candidate_ids,
            )
        cluster_count = int(self.db.scalar(select(func.count(IncidentCluster.id))) or 0)
        member_count = int(self.db.scalar(select(func.count(IncidentClusterMember.id))) or 0)
        return cluster_count, member_count
