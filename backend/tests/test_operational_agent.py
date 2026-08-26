import json
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.agents.gateway import LocalToolGateway, MCPToolGateway, connect_mcp_gateway
from app.agents.operational import OperationalAgent, _append_legal_source_details
from app.models import AuditEvent
from app.schemas import ComplaintExtractedData, ComplaintSubmissionCreate
from app.services.incidents import IncidentService
from app.tools.incidents import build_incident_tool_registry
from app.tools.registry import ToolAuthorizationError, ToolNotFoundError


class ScriptedResponses:
    def __init__(self):
        self.call_count = 0

    async def create(self, **kwargs):
        self.call_count += 1
        usage = SimpleNamespace(input_tokens=20, output_tokens=10)
        if self.call_count == 1:
            tool_call = SimpleNamespace(
                type="function_call",
                name="aggregate_incidents",
                arguments=json.dumps(
                    {
                        "group_by": "categoria_preliminar",
                        "district": "Llorente",
                        "category": None,
                        "synthetic_only": None,
                    }
                ),
                call_id="call-1",
            )
            return SimpleNamespace(
                id="response-1",
                output=[tool_call],
                output_text="",
                usage=usage,
            )
        return SimpleNamespace(
            id="response-2",
            output=[],
            output_text="La categoría más común en Llorente es ruido, con 2 incidentes.",
            usage=usage,
        )


class ScriptedAsyncOpenAI:
    def __init__(self):
        self.responses = ScriptedResponses()


class WrappedStructuredMCPResponse:
    def __init__(self):
        self.isError = False
        self.content = []
        self.structuredContent = {
            "result": json.dumps(
                {"sources": [{"source_id": "F1", "document_key": "reglamento-flores"}]}
            )
        }


class WrappedStructuredMCPSession:
    async def call_tool(self, name, arguments):
        return WrappedStructuredMCPResponse()


def create_incident(db_session, category: str = "ruido"):
    return IncidentService(db_session).create(
        ComplaintSubmissionCreate(
            name="Dato que no debe salir",
            identification="1-2345-6789",
            email="private@example.com",
            phone="8888-9999",
            ai_extracted_data=ComplaintExtractedData(
                descripcion_detallada="Reporte operativo de prueba.",
                relacion_incidente="testigo",
                categoria_preliminar=category,
                distrito="Llorente",
                direccion_exacta="Parque central",
                tipo_lugar="parque",
                fecha_hora_aproximada="ayer",
            ),
            truth_confirmation=True,
            data_usage_consent=True,
        )
    )


def test_registry_does_not_expose_contact_data_or_unknown_tools(db_session):
    incident = create_incident(db_session)
    registry = build_incident_tool_registry()

    result = registry.call(
        db_session,
        "get_incident",
        {"incident_id": incident.id},
        actor_role="admin",
    )

    serialized = str(result)
    assert "private@example.com" not in serialized
    assert "8888-9999" not in serialized
    assert "1-2345-6789" not in serialized
    assert "Dato que no debe salir" not in serialized
    with pytest.raises(ToolAuthorizationError):
        registry.call(
            db_session,
            "get_incident",
            {"incident_id": incident.id},
            actor_role="citizen",
        )
    with pytest.raises(ToolNotFoundError):
        registry.call(db_session, "execute_sql", {}, actor_role="admin")


def test_recurrent_patterns_tool_returns_recent_sanitized_patterns(db_session):
    create_incident(db_session)
    create_incident(db_session)
    create_incident(db_session)

    result = build_incident_tool_registry().call(
        db_session,
        "get_recurrent_patterns",
        {},
        actor_role="admin",
    )

    assert result["window_days"] == 30
    assert result["minimum_incidents"] == 3
    assert result["total_patterns"] == 1
    assert result["patterns"][0]["incident_count"] == 3
    assert "private@example.com" not in str(result)


@pytest.mark.asyncio
async def test_react_agent_uses_typed_tool_and_records_audit(db_session):
    create_incident(db_session, "ruido")
    create_incident(db_session, "ruido")
    agent = OperationalAgent(LocalToolGateway(db_session), client=ScriptedAsyncOpenAI())

    response = await agent.run("¿Cuál es la categoría más común en Llorente?")

    assert response.steps[0].tool_name == "aggregate_incidents"
    assert response.steps[0].success is True
    assert "ruido" in response.answer
    audit = db_session.scalar(select(AuditEvent).where(AuditEvent.trace_id == response.trace_id))
    assert audit is not None
    assert audit.details["argument_keys"] == [
        "category",
        "district",
        "group_by",
        "synthetic_only",
    ]


@pytest.mark.asyncio
async def test_mcp_server_exposes_domain_tools_without_sql():
    async with connect_mcp_gateway() as gateway:
        tools = await gateway.list_tools()

    names = {tool.name for tool in tools}
    assert "search_incidents" in names
    assert "find_related_incidents" in names
    assert "search_legal_sources" in names
    assert "get_legal_corpus_status" in names
    assert "execute_sql" not in names


@pytest.mark.asyncio
async def test_mcp_gateway_unwraps_fastmcp_structured_json_results():
    result = await MCPToolGateway(WrappedStructuredMCPSession()).call_tool(
        "search_legal_sources",
        {"query": "normativa"},
    )

    assert result["sources"][0]["source_id"] == "F1"


def test_operational_answer_appends_exact_legal_source_details():
    answer = _append_legal_source_details(
        "La municipalidad tiene una competencia expresa.",
        {
            "F1": {
                "source_id": "F1",
                "document_title": "Ley de prueba",
                "pdf_page": 12,
                "article_references": ["Artículo 8"],
                "allowed_classifications": [
                    "legal_obligation",
                    "municipal_authority",
                ],
            }
        },
    )

    assert "[F1] Ley de prueba" in answer
    assert "página PDF 12, Artículo 8" in answer
    assert "obligación legal, facultad municipal" in answer
