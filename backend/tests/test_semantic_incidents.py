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
