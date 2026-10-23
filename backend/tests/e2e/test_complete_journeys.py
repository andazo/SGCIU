from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.ai.intake import IntakeProvider
from app.auth import AuthService
from app.config import get_settings
from app.main import app
from app.models import LegalChunk, LegalDocument
from app.rag.generation import GroundedLegalAnswer, GroundedLegalFinding
from app.schemas import LegalIndexingResult, ModelUsage
from tests.fakes import extracted_data, intake_response

SCENARIOS_PATH = Path(__file__).resolve().parents[2] / "evaluation/flores_e2e_scenarios.json"
ADMIN_USERNAME = "administracion.e2e"
ADMIN_PASSWORD = "Contrasena E2E segura 2026"


def _load_scenarios() -> dict[str, object]:
    return json.loads(SCENARIOS_PATH.read_text(encoding="utf-8"))


class FloresScenarioIntakeProvider(IntakeProvider):
    """Deterministic OpenAI boundary double backed by realistic Flores scenarios."""

    model_name = "e2e-flores-intake-double"

    def __init__(self, scenarios: list[dict[str, object]]):
        self.scenarios = scenarios

    def analyze(
        self,
        messages,
        current_data,
        *,
        follow_up_count=0,
        emergency_guidance_already_shown=False,
    ):
        report = " ".join(message.content for message in messages if message.role == "user")
        scenario = next(
            (
                item
                for item in self.scenarios
                if str(item["match_text"]).casefold() in report.casefold()
            ),
            None,
        )
        if scenario is None:
            raise AssertionError(f"No existe escenario E2E para el relato: {report}")
        expected = scenario["expected"]
        data = extracted_data(
            descripcion_detallada=report,
            relacion_incidente=expected["relacion_incidente"],
            categoria_preliminar=expected["categoria_preliminar"],
            distrito=expected["distrito"],
            direccion_exacta=expected["direccion_exacta"],
            tipo_lugar=expected["tipo_lugar"],
            fecha_hora_aproximada=expected["fecha_hora_aproximada"],
            urgency=expected["urgency"],
        )
        data.entities.landmarks = list(expected["landmarks"])
        return intake_response(data)


class _ScriptedResponses:
    def __init__(self):
        self.calls = 0

    async def create(self, **kwargs):
        self.calls += 1
        usage = SimpleNamespace(input_tokens=80, output_tokens=30)
        if self.calls == 1:
            return SimpleNamespace(
                id="e2e-agent-1",
                output=[
                    SimpleNamespace(
                        type="function_call",
                        name="aggregate_incidents",
                        arguments=json.dumps(
                            {
                                "group_by": "distrito",
                                "district": "Barrantes",
                                "category": None,
                                "synthetic_only": True,
                            }
                        ),
                        call_id="e2e-tool-call",
                    )
                ],
                output_text="",
                usage=usage,
            )
        return SimpleNamespace(
            id="e2e-agent-2",
            output=[],
            output_text="Los casos sintéticos consultados se concentran en Barrantes.",
            usage=usage,
        )


class ScriptedAsyncOpenAI:
    def __init__(self, **kwargs):
        self.responses = _ScriptedResponses()


class CitedLegalAnswerDouble:
    model_name = "e2e-legal-answer-double"

    def generate(self, query, sources):
        return (
            GroundedLegalAnswer(
                summary="La fuente recuperada exige proteger los datos personales.",
                findings=[
                    GroundedLegalFinding(
                        classification="legal_obligation",
                        statement="El tratamiento debe respetar la finalidad informada.",
                        source_ids=["F1"],
                    )
                ],
                operational_guidance=[
                    "Limite el uso de los datos al registro y gestión del incidente."
                ],
            ),
            ModelUsage(input_tokens=120, output_tokens=45, estimated_cost_usd=0.0003),
        )


@pytest.fixture
def e2e_client(db_session, monkeypatch):
    dataset = _load_scenarios()
    provider = FloresScenarioIntakeProvider(dataset["scenarios"])
    monkeypatch.setattr("app.services.intake.get_intake_provider", lambda: provider)
    monkeypatch.setattr("app.agents.operational.AsyncOpenAI", ScriptedAsyncOpenAI)
    monkeypatch.setattr(
        "app.services.legal_rag.get_legal_answer_provider",
        lambda settings=None: CitedLegalAnswerDouble(),
    )
    monkeypatch.setenv("REQUIRE_ADMIN_AUTH", "true")
    monkeypatch.setenv("TOOL_TRANSPORT", "local")
    monkeypatch.delenv("ADMIN_API_KEY", raising=False)
    get_settings.cache_clear()
    AuthService(db_session).create_user(
        ADMIN_USERNAME,
        ADMIN_PASSWORD,
        "administrative",
    )
    with TestClient(app) as client:
        yield client, dataset
    get_settings.cache_clear()


def _admin_headers(client: TestClient) -> dict[str, str]:
    login = client.post(
        "/v1/auth/login",
        json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
    )
    assert login.status_code == 200
    assert login.json()["user"]["role"] == "administrative"
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _scenario(dataset: dict[str, object], channel: str) -> dict[str, object]:
    return next(item for item in dataset["scenarios"] if item["channel"] == channel)


def _submit_public_intake(
    client: TestClient,
    scenario: dict[str, object],
    *,
    registration_mode: str,
) -> dict[str, object]:
    start = client.post(
        "/v1/intake/sessions",
        json={"registration_mode": registration_mode},
    )
    assert start.status_code == 201
    assert "9-1-1" in start.json()["emergency_notice"]
    session_id = start.json()["session_id"]
    client.headers["X-Intake-Token"] = start.json()["access_token"]

    analyzed = client.post(
        f"/v1/intake/sessions/{session_id}/messages",
        json={"content": scenario["report"]},
    )
    assert analyzed.status_code == 200
    assert analyzed.json()["is_complete"] is True
    assert analyzed.json()["extracted_data"]["distrito"] == scenario["expected"]["distrito"]

    restored = client.get(f"/v1/intake/sessions/{session_id}")
    assert restored.status_code == 200
    assert restored.json()["messages"] == analyzed.json()["messages"]

    submitted = client.post(
        f"/v1/intake/sessions/{session_id}/submit",
        json={
            "name": "Persona ficticia E2E",
            "identification": "E2E-NO-REAL",
            "email": "persona-e2e@example.com",
            "phone": "0000-0000",
            "truth_confirmation": True,
            "data_usage_consent": True,
        },
    )
    assert submitted.status_code == 201
    return submitted.json()


@pytest.mark.e2e
def test_complete_citizen_module(e2e_client):
    client, dataset = e2e_client
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/ready").json() == {"status": "ready"}

    identified = _submit_public_intake(
        client,
        _scenario(dataset, "citizen_complete"),
        registration_mode="complete",
    )
    assert identified["name"] == "Persona ficticia E2E"
    assert identified["analysis_metadata"]["anonymous"] is False
    assert identified["police_input"] is False

    anonymous = _submit_public_intake(
        client,
        _scenario(dataset, "citizen_anonymous"),
        registration_mode="anonymous",
    )
    assert anonymous["name"] is None
    assert anonymous["identification"] is None
    assert anonymous["email"] is None
    assert anonymous["phone"] is None
    assert anonymous["analysis_metadata"]["anonymous"] is True

    assert client.get("/v1/incidents").status_code == 401


def _admin_incident_payload(case_number: int, *, review=False, high_priority=False):
    description = (
        "Caso ficticio E2E: residuos abandonados en la vía pública de barrio Ugalde, "
        "Barrantes, 50 metros al oeste de la entrada del barrio."
    )
    return {
        "entered_by_badge": "E2E-ADMIN-001",
        "police_input": True,
        "ai_extracted_data": {
            "descripcion_detallada": description,
            "relacion_incidente": "testigo",
            "categoria_preliminar": "vandalismo" if high_priority else "basura_o_contaminacion",
            "distrito": "Barrantes",
            "direccion_exacta": (
                "Barrio Ugalde, 50 metros al oeste de la entrada del barrio"
            ),
            "tipo_lugar": "otro",
            "fecha_hora_aproximada": "hoy",
            "urgency": "alta" if high_priority else "baja",
            "entities": {"landmarks": ["entrada de barrio Ugalde"]},
        },
        "analysis_metadata": {
            "synthetic": True,
            "e2e_case_id": f"FLO-E2E-{case_number:03d}",
        },
        "requires_human_review": review,
        "review_reason": "Ubicación pendiente de validación." if review else None,
        "truth_confirmation": True,
        "data_usage_consent": True,
    }


def _seed_legal_source(db_session):
    from tests.fakes import LocalEmbeddingDouble

    provider = LocalEmbeddingDouble()
    content = (
        "Los datos personales deben tratarse respetando la finalidad informada y las "
        "medidas de seguridad aplicables."
    )
    document = LegalDocument(
        document_key="e2e-proteccion-datos",
        title="Ley de Protección de la Persona frente al Tratamiento de sus Datos Personales",
        short_title="Ley 8968",
        source_filename="23_ley_8968_proteccion_datos_personales.pdf",
        source_sha256="e" * 64,
        authority="Asamblea Legislativa de Costa Rica",
        jurisdiction="Costa Rica",
        document_type="ley",
        corpus_version="2026.08.2",
        page_count=20,
        priority=1,
        status="active",
        document_metadata={
            "source_category": "national_legislation",
            "legal_force": "binding",
            "authority_scope": "general_national",
            "allowed_classifications": ["legal_obligation"],
        },
    )
    db_session.add(document)
    db_session.flush()
    db_session.add(
        LegalChunk(
            document_id=document.id,
            chunk_index=0,
            page_number=7,
            article_references=["Artículo 4"],
            content=content,
            content_hash=hashlib.sha256(content.encode()).hexdigest(),
            estimated_tokens=30,
            embedding=provider.embed(content),
            embedding_model=provider.model_name,
            corpus_version="2026.08.2",
            chunk_metadata={},
        )
    )
    db_session.commit()


@pytest.mark.e2e
def test_complete_administrative_module(e2e_client, db_session, monkeypatch):
    client, dataset = e2e_client
    assert client.get("/v1/incidents").status_code == 401
    headers = _admin_headers(client)
    assert client.get("/v1/auth/me", headers=headers).status_code == 200

    internal = _scenario(dataset, "staff_internal")
    started = client.post("/v1/internal-intake/sessions", headers=headers)
    assert started.status_code == 201
    session_id = started.json()["session_id"]
    analyzed = client.post(
        f"/v1/internal-intake/sessions/{session_id}/messages",
        headers=headers,
        json={"content": internal["report"]},
    )
    assert analyzed.status_code == 200
    submitted = client.post(
        f"/v1/internal-intake/sessions/{session_id}/submit",
        headers=headers,
        json={
            "entered_by_badge": "E2E-ADMIN-001",
            "truth_confirmation": True,
            "data_usage_consent": True,
        },
    )
    assert submitted.status_code == 201
    assert submitted.json()["police_input"] is True

    created = []
    for index in range(1, 4):
        response = client.post(
            "/v1/incidents",
            headers=headers,
            json=_admin_incident_payload(index),
        )
        assert response.status_code == 201
        created.append(response.json())

    review_incident = client.post(
        "/v1/incidents",
        headers=headers,
        json=_admin_incident_payload(10, review=True),
    )
    assert review_incident.status_code == 201
    priority_incident = client.post(
        "/v1/incidents",
        headers=headers,
        json=_admin_incident_payload(11, high_priority=True),
    )
    assert priority_incident.status_code == 201

    listing = client.get(
        "/v1/incidents?district=Barrantes&limit=20",
        headers=headers,
    )
    assert listing.status_code == 200
    assert listing.json()["total"] >= 6
    incident_id = created[0]["id"]
    assert client.get(f"/v1/incidents/{incident_id}", headers=headers).status_code == 200
    assert (
        client.post(f"/v1/incidents/{incident_id}/semantic-index", headers=headers).status_code
        == 204
    )
    related = client.get(f"/v1/incidents/{incident_id}/related", headers=headers)
    assert related.status_code == 200
    assert related.json()["items"]

    recalculated = client.post("/v1/incidents/clusters/recalculate", headers=headers)
    assert recalculated.status_code == 200
    assert recalculated.json()["embeddings_failed"] == 0
    candidates = client.get("/v1/incidents/clusters/candidates", headers=headers)
    recurrent = client.get("/v1/incidents/clusters/recurrent", headers=headers)
    assert candidates.status_code == 200
    assert recurrent.status_code == 200
    assert recurrent.json()

    reviews = client.get("/v1/reviews?status=pending", headers=headers)
    assert reviews.status_code == 200
    assert reviews.json()
    review_id = reviews.json()[0]["id"]
    assert client.post(
        f"/v1/reviews/{review_id}/transition",
        headers=headers,
        json={"action": "start", "notes": "Revisión E2E iniciada."},
    ).status_code == 200
    assert client.post(
        f"/v1/reviews/{review_id}/resolve",
        headers=headers,
        json={"notes": "Datos verificados durante la prueba E2E."},
    ).status_code == 200

    highlights = client.get("/v1/reviews/highlights?status=pending", headers=headers)
    assert highlights.status_code == 200
    assert highlights.json()
    highlight_id = highlights.json()[0]["id"]
    assert client.post(
        f"/v1/reviews/highlights/{highlight_id}/transition",
        headers=headers,
        json={"action": "resolve", "notes": "Resaltado atendido en prueba E2E."},
    ).status_code == 200
    assessed = client.post("/v1/reviews/assess-pending", headers=headers)
    assert assessed.status_code == 200

    operational_session = client.post("/v1/operational/sessions", headers=headers)
    assert operational_session.status_code == 201
    operational_id = operational_session.json()["session_id"]
    agent_answer = client.post(
        f"/v1/operational/sessions/{operational_id}/messages",
        headers=headers,
        json={"query": "¿Cuántos incidentes sintéticos hay en Barrantes?"},
    )
    assert agent_answer.status_code == 200
    assert agent_answer.json()["steps"][0]["tool_name"] == "aggregate_incidents"
    assert client.get(
        f"/v1/operational/sessions/{operational_id}", headers=headers
    ).status_code == 200
    assert client.post(
        "/v1/reviews/feedback",
        headers=headers,
        json={
            "trace_id": agent_answer.json()["trace_id"],
            "rating": 5,
            "comment": "Respuesta correcta para el escenario sintético.",
        },
    ).status_code == 201

    _seed_legal_source(db_session)
    from tests.fakes import LocalEmbeddingDouble

    monkeypatch.setattr(
        "app.rag.retrieval.get_legal_embedding_provider",
        lambda settings=None: LocalEmbeddingDouble(),
    )
    monkeypatch.setattr(
        "app.rag.corpus.LegalCorpusIndexer.index_all",
        lambda self, force=False: LegalIndexingResult(
            corpus_version="2026.08.2",
            documents_found=27,
            documents_indexed=0,
            documents_skipped=27,
            documents_failed=0,
            embeddings_created=0,
        ),
    )
    assert client.get("/v1/legal-rag/corpus", headers=headers).status_code == 200
    assert client.post(
        "/v1/legal-rag/corpus/index",
        headers=headers,
        json={"force": False},
    ).status_code == 200
    legal_answer = client.post(
        "/v1/legal-rag/query",
        headers=headers,
        json={
            "query": "¿Cómo deben protegerse los datos de una denuncia?",
            "audience": "administrative",
            "operational_context": "Registro ciudadano en el cantón de Flores.",
        },
    )
    assert legal_answer.status_code == 200
    assert legal_answer.json()["citations"][0]["pdf_page"] == 7
    assert legal_answer.json()["insufficient_evidence"] is False

    assert client.post("/v1/auth/logout", headers=headers).status_code == 204
    assert client.get("/v1/auth/me", headers=headers).status_code == 401
