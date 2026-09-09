from dataclasses import replace
from datetime import UTC, datetime, timedelta

from app.config import get_settings
from app.schemas import ComplaintExtractedData, ComplaintSubmissionCreate, IncidentEntities
from app.services.incidents import IncidentService
from app.services.semantic import SemanticIncidentService, canonical_incident_text
from tests.fakes import LocalEmbeddingDouble


def incident_payload(
    description: str,
    address: str,
    *,
    incident_datetime: str | None = None,
) -> ComplaintSubmissionCreate:
    return ComplaintSubmissionCreate(
        ai_extracted_data=ComplaintExtractedData(
            descripcion_detallada=description,
            relacion_incidente="testigo",
            categoria_preliminar="ruido",
            distrito="Llorente",
            direccion_exacta=address,
            tipo_lugar="parque",
            fecha_hora_aproximada="ayer a las 22:00",
            incident_datetime=incident_datetime,
            incident_datetime_precision="exact" if incident_datetime else "unknown",
            incident_datetime_source="explicit" if incident_datetime else "unknown",
        ),
        truth_confirmation=True,
        data_usage_consent=True,
    )


def test_similar_incidents_are_indexed_and_grouped(db_session):
    first = IncidentService(db_session).create(
        incident_payload(
            "Fiesta con música a alto volumen durante la noche.",
            "100 metros norte de la escuela",
        )
    )
    second = IncidentService(db_session).create(
        incident_payload(
            "Fiesta con música a alto volumen durante la noche.",
            "100 metros norte de la escuela",
        )
    )

    service = SemanticIncidentService(
        db_session,
        provider=LocalEmbeddingDouble(),
    )
    related = service.find_related(second, top_k=3)
    clusters = service.list_clusters()

    assert related[0].incident.id == first.id
    assert related[0].similarity_score >= 0.78
    assert len(clusters) == 1
    assert {member.incident_id for member in clusters[0].members} == {first.id, second.id}


def test_canonical_text_redacts_people_and_contact_data(db_session):
    payload = incident_payload(
        "Juan Pérez llamó desde 8888-9999 y escribió a juan@example.com.",
        "Parque central",
    )
    payload.ai_extracted_data.entities = IncidentEntities(people=["Juan Pérez"])
    incident = IncidentService(db_session).create(payload)

    text = canonical_incident_text(incident)

    assert "Juan Pérez" not in text
    assert "8888-9999" not in text
    assert "juan@example.com" not in text
    assert "[PERSONA]" in text


def test_manual_recalculation_rebuilds_embeddings_and_clusters(db_session):
    IncidentService(db_session).create(
        incident_payload("Ruido recurrente frente a la escuela.", "Frente a la escuela")
    )
    IncidentService(db_session).create(
        incident_payload("Ruido recurrente frente a la escuela.", "Frente a la escuela")
    )

    result = SemanticIncidentService(
        db_session,
        provider=LocalEmbeddingDouble(),
    ).recalculate_all()

    assert result.incidents_found == 2
    assert result.embeddings_updated == 2
    assert result.embeddings_failed == 0
    assert result.clusters_rebuilt == 1
    assert result.cluster_members == 2


def test_recurrent_patterns_require_three_recent_similar_incidents(db_session):
    for description in (
        "Fiesta con música alta frente a la escuela.",
        "Ruido fuerte de una fiesta cerca de la escuela.",
        "Música a alto volumen en las cercanías de la escuela.",
    ):
        IncidentService(db_session).create(
            incident_payload(description, "100 metros norte de la escuela")
        )

    patterns = SemanticIncidentService(
        db_session,
        provider=LocalEmbeddingDouble(),
    ).list_recurrent_patterns()

    assert len(patterns) == 1
    assert len(patterns[0].members) == 3
    assert all(
        member.incident.embedding_record.location_embedding for member in patterns[0].members
    )


def test_clustering_uses_occurrence_time_when_reports_arrive_months_apart(db_session):
    first = IncidentService(db_session).create(
        incident_payload(
            "Música alta recurrente frente a la misma escuela.",
            "100 metros norte de la escuela",
            incident_datetime="2026-06-01T22:00:00-06:00",
        ),
        recorded_at=datetime(2026, 6, 2, tzinfo=UTC),
    )
    second = IncidentService(db_session).create(
        incident_payload(
            "Música alta recurrente frente a la misma escuela.",
            "100 metros norte de la escuela",
            incident_datetime="2026-06-02T22:00:00-06:00",
        ),
        recorded_at=datetime(2026, 9, 1, tzinfo=UTC),
    )

    related = SemanticIncidentService(db_session, provider=LocalEmbeddingDouble()).find_related(
        second
    )

    assert [item.incident.id for item in related] == [first.id]


def test_clustering_rejects_distant_events_registered_together(db_session):
    first = IncidentService(db_session).create(
        incident_payload(
            "Música alta recurrente frente a la misma escuela.",
            "100 metros norte de la escuela",
            incident_datetime="2026-03-01T22:00:00-06:00",
        ),
        recorded_at=datetime(2026, 9, 1, tzinfo=UTC),
    )
    second = IncidentService(db_session).create(
        incident_payload(
            "Música alta recurrente frente a la misma escuela.",
            "100 metros norte de la escuela",
            incident_datetime="2026-08-01T22:00:00-06:00",
        ),
        recorded_at=datetime(2026, 9, 1, tzinfo=UTC),
    )

    related = SemanticIncidentService(db_session, provider=LocalEmbeddingDouble()).find_related(
        second
    )

    assert first.id not in {item.incident.id for item in related}


def test_recurrent_pattern_honors_requested_window(db_session):
    occurred_at = datetime.now(UTC) - timedelta(days=60)
    for index in range(3):
        IncidentService(db_session).create(
            incident_payload(
                f"Música alta recurrente frente a la misma escuela caso {index}.",
                "100 metros norte de la escuela",
                incident_datetime=occurred_at.isoformat(),
            )
        )
    service = SemanticIncidentService(db_session, provider=LocalEmbeddingDouble())

    assert service.list_recurrent_patterns(window_days=30) == []
    assert len(service.list_recurrent_patterns(window_days=90)) == 1


def test_incident_date_filters_distinguish_occurrence_from_registration(db_session):
    incident = IncidentService(db_session).create(
        incident_payload(
            "Música alta recurrente frente a la misma escuela.",
            "100 metros norte de la escuela",
            incident_datetime="2026-06-15T22:00:00-06:00",
        ),
        recorded_at=datetime(2026, 9, 1, tzinfo=UTC),
    )
    service = IncidentService(db_session)

    occurred, occurred_total = service.list(
        created_from=datetime(2026, 6, 1).date(),
        created_to=datetime(2026, 6, 30).date(),
        date_basis="occurrence",
    )
    registered, registered_total = service.list(
        created_from=datetime(2026, 6, 1).date(),
        created_to=datetime(2026, 6, 30).date(),
        date_basis="registration",
    )

    assert occurred_total == 1
    assert occurred[0].id == incident.id
    assert registered_total == 0
    assert registered == []


def test_bridge_incident_merges_previously_separate_clusters(db_session):
    incidents = [
        IncidentService(db_session).create(
            incident_payload(
                f"Reporte semántico controlado {index}.",
                "Ubicación controlada",
                incident_datetime="2026-08-10T20:00:00-06:00",
            )
        )
        for index in range(5)
    ]
    vectors = ([1.0, 0.0], [1.0, 0.0], [0.0, 1.0], [0.0, 1.0], [0.7071, 0.7071])
    for incident, vector in zip(incidents, vectors, strict=True):
        incident.embedding_record.embedding = list(vector)
        incident.embedding_record.location_embedding = list(vector)
    db_session.commit()
    settings = replace(get_settings(), similarity_threshold=0.75)
    service = SemanticIncidentService(
        db_session,
        provider=LocalEmbeddingDouble(dimensions=2),
        settings=settings,
    )
    service.rebuild_clusters(incidents[:4])

    assert len(service.list_clusters()) == 2

    service.update_candidate_cluster(
        incidents[4], candidate_incident_ids={incident.id for incident in incidents}
    )
    clusters = service.list_clusters()

    assert len(clusters) == 1
    assert {member.incident_id for member in clusters[0].members} == {
        incident.id for incident in incidents
    }
