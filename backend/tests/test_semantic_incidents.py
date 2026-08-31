from app.schemas import ComplaintExtractedData, ComplaintSubmissionCreate, IncidentEntities
from app.services.incidents import IncidentService
from app.services.semantic import SemanticIncidentService, canonical_incident_text
from tests.fakes import LocalEmbeddingDouble


def incident_payload(description: str, address: str) -> ComplaintSubmissionCreate:
    return ComplaintSubmissionCreate(
        ai_extracted_data=ComplaintExtractedData(
            descripcion_detallada=description,
            relacion_incidente="testigo",
            categoria_preliminar="ruido",
            distrito="Llorente",
            direccion_exacta=address,
            tipo_lugar="parque",
            fecha_hora_aproximada="ayer a las 22:00",
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
