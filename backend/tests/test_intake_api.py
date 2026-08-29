from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_versioned_intake_api_flow():
    start = client.post("/v1/intake/sessions")
    assert start.status_code == 201
    assert "no es un servicio de atención de emergencias" in start.json()["emergency_notice"]
    session_id = start.json()["session_id"]

    analyzed = client.post(
        f"/v1/intake/sessions/{session_id}/messages",
        json={
            "content": (
                "Ayer vi mucho ruido en un parque de Llorente. "
                "Ubicación: 100 metros norte de la escuela."
            )
        },
    )
    assert analyzed.status_code == 200
    assert analyzed.json()["is_complete"] is True

    submitted = client.post(
        f"/v1/intake/sessions/{session_id}/submit",
        json={"truth_confirmation": True, "data_usage_consent": True},
    )
    assert submitted.status_code == 201
    assert submitted.json()["prompt_version"] == "intake-v4"

    incidents = client.get("/v1/incidents")
    assert incidents.status_code == 200
    assert incidents.json()["total"] == 1


def test_internal_intake_api_marks_source_and_badge():
    start = client.post("/v1/internal-intake/sessions")
    assert start.status_code == 201
    session_id = start.json()["session_id"]

    analyzed = client.post(
        f"/v1/internal-intake/sessions/{session_id}/messages",
        json={"content": "Se recibió una denuncia verbal por ruido frente a una escuela."},
    )
    assert analyzed.status_code == 200
    assert analyzed.json()["is_complete"] is True

    submitted = client.post(
        f"/v1/internal-intake/sessions/{session_id}/submit",
        json={
            "entered_by_badge": "POL-042",
            "truth_confirmation": True,
            "data_usage_consent": True,
        },
    )

    assert submitted.status_code == 201
    assert submitted.json()["police_input"] is True
    assert submitted.json()["entered_by_badge"] == "POL-042"
