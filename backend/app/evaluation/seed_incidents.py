from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from pydantic import Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.intake import DESIRED_FIELDS
from app.db import SessionLocal
from app.models import ComplaintSubmission, IncidentCluster, IncidentEmbedding
from app.schemas import (
    CategoriaPreliminar,
    ComplaintExtractedData,
    ComplaintSubmissionCreate,
    Distrito,
    EntityEvidence,
    IncidentEntities,
    IntakeFieldObservation,
    RelacionIncidente,
    StrictModel,
    TipoLugar,
    Urgencia,
)
from app.services.incidents import IncidentService
from app.services.semantic import SemanticIncidentService

DEFAULT_DATASET = (
    Path(__file__).resolve().parents[2] / "evaluation" / "flores_synthetic_incidents.json"
)
SYNTHETIC_SOURCE = "flores_synthetic_admin_seed"


class SyntheticIncidentRecord(StrictModel):
    case_id: str = Field(pattern=r"^FLO-(SJ|BA|LL)-\d{3}$")
    descripcion_detallada: str = Field(min_length=20)
    relacion_incidente: RelacionIncidente
    categoria_preliminar: CategoriaPreliminar
    distrito: Distrito
    direccion_exacta: str = Field(min_length=5)
    tipo_lugar: TipoLugar
    fecha_hora_aproximada: str = Field(min_length=5)
    urgency: Urgencia
    vehicles: list[str] = Field(default_factory=list)
    objects: list[str] = Field(default_factory=list)
    establishments: list[str] = Field(default_factory=list)
    landmarks: list[str] = Field(default_factory=list)
    requires_human_review: bool = False
    review_reason: str | None = None

    @model_validator(mode="after")
    def review_cases_require_a_reason(self):
        if self.requires_human_review and not self.review_reason:
            raise ValueError("Los casos de revisión humana deben explicar el motivo.")
        return self


class SyntheticIncidentDataset(StrictModel):
    version: str
    description: str
    sources: list[str]
    incidents: list[SyntheticIncidentRecord]

    @model_validator(mode="after")
    def case_ids_must_be_unique(self):
        case_ids = [incident.case_id for incident in self.incidents]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("Los identificadores sintéticos deben ser únicos.")
        return self


@dataclass(frozen=True, slots=True)
class SeedResult:
    dataset_version: str
    total_cases: int
    created: int
    skipped_existing: int
    indexed: int
    pending_embeddings: int
    candidate_clusters_in_database: int
    incident_ids: list[int]


def load_seed_dataset(path: Path = DEFAULT_DATASET) -> SyntheticIncidentDataset:
    return SyntheticIncidentDataset.model_validate_json(path.read_text(encoding="utf-8"))


def _entity_evidence(record: SyntheticIncidentRecord) -> list[EntityEvidence]:
    evidence: list[EntityEvidence] = []
    for entity_type, values in (
        ("vehicle", record.vehicles),
        ("object", record.objects),
        ("establishment", record.establishments),
        ("landmark", record.landmarks),
    ):
        evidence.extend(
            EntityEvidence(entity_type=entity_type, value=value, source_text=value)
            for value in values
        )
    return evidence


def _extracted_data(record: SyntheticIncidentRecord) -> ComplaintExtractedData:
    data = ComplaintExtractedData(
        descripcion_detallada=record.descripcion_detallada,
        relacion_incidente=record.relacion_incidente,
        categoria_preliminar=record.categoria_preliminar,
        distrito=record.distrito,
        direccion_exacta=record.direccion_exacta,
        tipo_lugar=record.tipo_lugar,
        fecha_hora_aproximada=record.fecha_hora_aproximada,
        urgency=record.urgency,
        entities=IncidentEntities(
            vehicles=record.vehicles,
            objects=record.objects,
            establishments=record.establishments,
            landmarks=record.landmarks,
            temporal_references=[record.fecha_hora_aproximada],
            evidence=_entity_evidence(record),
        ),
    )
    for field in DESIRED_FIELDS:
        value = getattr(data, field)
        setattr(
            data.field_states,
            field,
            IntakeFieldObservation(status="known", confidence=1.0, evidence=str(value)),
        )
        setattr(data.confidence_by_field, field, 1.0)
    return data


def _summary(record: SyntheticIncidentRecord) -> str:
    return (
        f"Caso sintético {record.case_id}. Se reportó un incidente clasificado "
        f"preliminarmente como {record.categoria_preliminar} en {record.distrito}. "
        f"La ubicación indicada es {record.direccion_exacta}. "
        f"Según el escenario de prueba, {record.descripcion_detallada}"
    )


def _existing_seed_incidents(db: Session) -> dict[str, ComplaintSubmission]:
    existing: dict[str, ComplaintSubmission] = {}
    for incident in db.scalars(select(ComplaintSubmission)):
        metadata = incident.analysis_metadata or {}
        if metadata.get("source") != SYNTHETIC_SOURCE:
            continue
        case_id = metadata.get("synthetic_case_id")
        if isinstance(case_id, str):
            existing[case_id] = incident
    return existing


def seed_incidents(
    db: Session,
    dataset: SyntheticIncidentDataset,
    *,
    ensure_semantic_index: bool = True,
) -> SeedResult:
    existing = _existing_seed_incidents(db)
    created = 0
    skipped = 0
    incidents: list[ComplaintSubmission] = []
    service = IncidentService(db)

    for record in dataset.incidents:
        incident = existing.get(record.case_id)
        if incident is not None:
            skipped += 1
            incidents.append(incident)
            continue
        incident = service.create(
            ComplaintSubmissionCreate(
                ai_extracted_data=_extracted_data(record),
                ai_summary_text=_summary(record),
                analysis_metadata={
                    "source": SYNTHETIC_SOURCE,
                    "dataset_version": dataset.version,
                    "synthetic_case_id": record.case_id,
                    "synthetic": True,
                },
                requires_human_review=record.requires_human_review,
                review_reason=record.review_reason,
                model_name="synthetic-dataset",
                prompt_version=f"synthetic-seed-{dataset.version}",
                truth_confirmation=True,
                data_usage_consent=True,
            )
        )
        created += 1
        incidents.append(incident)

    incident_ids = [incident.id for incident in incidents]
    if ensure_semantic_index:
        indexed_ids = set(
            db.scalars(
                select(IncidentEmbedding.incident_id).where(
                    IncidentEmbedding.incident_id.in_(incident_ids)
                )
            )
        )
        pending = [incident for incident in incidents if incident.id not in indexed_ids]
        if pending:
            semantic_service = SemanticIncidentService(db)
            for incident in pending:
                semantic_service.process_incident(incident)

    indexed = int(
        db.scalar(
            select(func.count(IncidentEmbedding.id)).where(
                IncidentEmbedding.incident_id.in_(incident_ids)
            )
        )
        or 0
    )
    cluster_count = int(db.scalar(select(func.count(IncidentCluster.id))) or 0)
    return SeedResult(
        dataset_version=dataset.version,
        total_cases=len(dataset.incidents),
        created=created,
        skipped_existing=skipped,
        indexed=indexed,
        pending_embeddings=len(incident_ids) - indexed,
        candidate_clusters_in_database=cluster_count,
        incident_ids=incident_ids,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Carga incidentes sintéticos del cantón de Flores para pruebas administrativas."
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument(
        "--without-embeddings",
        action="store_true",
        help="Carga los incidentes sin exigir que todos queden indexados semánticamente.",
    )
    args = parser.parse_args()
    dataset = load_seed_dataset(args.dataset)
    with SessionLocal() as db:
        result = seed_incidents(
            db,
            dataset,
            ensure_semantic_index=not args.without_embeddings,
        )
    print(json.dumps(asdict(result), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
