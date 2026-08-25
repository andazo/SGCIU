from app.ai.incident_assessment import _sanitized_incident_payload
from app.schemas import ComplaintExtractedData, EntityEvidence, IncidentEntities


def test_administrative_assessment_payload_excludes_contact_and_people():
    data = ComplaintExtractedData(
        descripcion_detallada=("Juan Pérez llamó desde 8888-9999 y escribió a juan@example.com."),
        entities=IncidentEntities(
            people=["Juan Pérez"],
            evidence=[
                EntityEvidence(
                    entity_type="person",
                    value="Juan Pérez",
                    source_text="Juan Pérez",
                )
            ],
        ),
    )

    payload = _sanitized_incident_payload(data)

    assert "Juan Pérez" not in payload["descripcion_detallada"]
    assert "8888-9999" not in payload["descripcion_detallada"]
    assert "juan@example.com" not in payload["descripcion_detallada"]
    assert payload["entities"]["people"] == []
    assert payload["entities"]["evidence"] == []
