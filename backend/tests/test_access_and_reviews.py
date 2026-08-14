from dataclasses import replace

from fastapi.testclient import TestClient
from sqlalchemy import select

import app.api.dependencies as dependencies
from app.api.dependencies import validate_admin_key
from app.cli import parse_args
from app.config import get_settings
from app.main import app
from app.models import HumanReview
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
    review = HumanReview(incident_id=incident.id, reason="Clasificación ambigua.")
    db_session.add(review)
    db_session.commit()
    db_session.refresh(review)

    resolved = ReviewService(db_session).resolve(review.id, "Validado por el oficial de turno.")

    assert resolved.status == "resolved"
    assert incident.status == "reviewed"
    assert incident.requires_human_review is False
    assert db_session.scalar(select(HumanReview).where(HumanReview.id == review.id)) is resolved


def test_cli_accepts_explicit_role_and_mcp_transport():
    args = parse_args(["--role", "admin", "--transport", "mcp"])

    assert args.role == "admin"
    assert args.transport == "mcp"
