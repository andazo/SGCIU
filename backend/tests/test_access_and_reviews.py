from dataclasses import replace

from fastapi.testclient import TestClient
from sqlalchemy import select

import app.api.dependencies as dependencies
from app.api.dependencies import validate_admin_key
from app.cli import parse_args
from app.config import get_settings
from app.main import app
from app.models import HumanReview, IncidentHighlight
from app.schemas import ComplaintExtractedData, ComplaintSubmissionCreate
from app.services.incidents import IncidentService
from app.services.reviews import ReviewService


def test_admin_key_validation_is_constant_policy():
    protected = replace(
        get_settings(),
        require_admin_auth=True,
        admin_api_key="test-secret",
    )
    development = replace(protected, require_admin_auth=False)

    assert validate_admin_key("test-secret", protected) is True
    assert validate_admin_key("wrong", protected) is False
    assert validate_admin_key(None, protected) is False
    assert validate_admin_key(None, development) is True


def test_admin_endpoint_rejects_missing_key(monkeypatch):
    protected = replace(
        get_settings(),
        require_admin_auth=True,
        admin_api_key="test-secret",
    )
    monkeypatch.setattr(dependencies, "get_settings", lambda: protected)
    client = TestClient(app)

    assert client.get("/v1/incidents").status_code == 401
    assert client.get("/v1/incidents", headers={"X-Admin-Key": "test-secret"}).status_code == 200


def test_pending_assessment_endpoint_returns_batch_result(monkeypatch):
    monkeypatch.setattr(
        "app.api.routes.reviews.ReviewService.assess_pending_incidents",
        lambda _service: (4, 3, 1),
    )

    response = TestClient(app).post("/v1/reviews/assess-pending")

    assert response.status_code == 200
    assert response.json() == {"pending": 4, "completed": 3, "failed": 1}


def test_review_resolution_updates_incident_state(db_session):
    incident = IncidentService(db_session).create(
        ComplaintSubmissionCreate(
            ai_extracted_data=ComplaintExtractedData(
                descripcion_detallada="Incidente que requiere validación.",
                relacion_incidente="testigo",
                categoria_preliminar="otro",
                distrito="Barrantes",
                direccion_exacta="Parque de Barrantes",
                tipo_lugar="parque",
                fecha_hora_aproximada="hoy",
            ),
            requires_human_review=True,
            review_reason="Clasificación ambigua.",
            truth_confirmation=True,
            data_usage_consent=True,
        )
    )
    review = db_session.scalar(
        select(HumanReview).where(
            HumanReview.incident_id == incident.id,
            HumanReview.status == "pending",
        )
    )
    assert review is not None

    resolved = ReviewService(db_session).resolve(review.id, "Validado por el oficial de turno.")

    assert resolved.status == "resolved"
    assert incident.status == "reviewed"
    assert incident.requires_human_review is False
    assert db_session.scalar(select(HumanReview).where(HumanReview.id == review.id)) is resolved


def test_incident_can_have_highlight_and_quality_review_and_dismiss_preserves_it(db_session):
    incident = IncidentService(db_session).create(
        ComplaintSubmissionCreate(
            ai_extracted_data=ComplaintExtractedData(
                descripcion_detallada="Se reportó un robo violento, pero falta la dirección.",
                relacion_incidente="testigo",
                categoria_preliminar="robo",
                distrito="San Joaquin",
                fecha_hora_aproximada="anoche",
                urgency="alta",
            ),
            requires_human_review=True,
            review_reason="La ubicación es insuficiente.",
            truth_confirmation=True,
            data_usage_consent=True,
        )
    )

    review = db_session.scalar(select(HumanReview).where(HumanReview.incident_id == incident.id))
    highlight = db_session.scalar(
        select(IncidentHighlight).where(IncidentHighlight.incident_id == incident.id)
    )

    assert review is not None
    assert highlight is not None
    assert review.contact_available is False
    assert any(
        action["code"] == "dismiss_if_unrecoverable"
        for action in review.recommended_actions
    )
    assert highlight.status == "pending"

    dismissed = ReviewService(db_session).transition_review(
        review.id,
        "dismiss",
        "No existe contacto ni información suficiente para aclarar la ubicación.",
    )

    assert dismissed.status == "dismissed"
    assert incident.status == "insufficient_information"
    assert incident.requires_human_review is False
    assert db_session.get(type(incident), incident.id) is incident
    assert highlight.status == "pending"


def test_cli_accepts_explicit_role_and_mcp_transport():
    args = parse_args(["--role", "admin", "--transport", "mcp"])

    assert args.role == "admin"
    assert args.transport == "mcp"
