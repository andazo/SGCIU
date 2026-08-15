import pytest
from sqlalchemy import select

from app.agents.gateway import LocalToolGateway, connect_mcp_gateway
from app.agents.operational import OperationalAgent
from app.models import AuditEvent
from app.schemas import ComplaintExtractedData, ComplaintSubmissionCreate
from app.services.incidents import IncidentService
from app.tools.incidents import build_incident_tool_registry
from app.tools.registry import ToolAuthorizationError, ToolNotFoundError


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


@pytest.mark.asyncio
async def test_react_agent_uses_typed_tool_and_records_audit(db_session):
    create_incident(db_session, "ruido")
    create_incident(db_session, "ruido")
    agent = OperationalAgent(LocalToolGateway(db_session))

    response = await agent.run("¿Cuál es la categoría más común en Llorente?")

    assert response.steps[0].tool_name == "aggregate_incidents"
    assert response.steps[0].success is True
    assert "ruido" in response.answer
    audit = db_session.scalar(select(AuditEvent).where(AuditEvent.trace_id == response.trace_id))
    assert audit is not None
    assert audit.details["argument_keys"] == ["category", "district", "group_by"]


@pytest.mark.asyncio
async def test_mcp_server_exposes_domain_tools_without_sql():
    async with connect_mcp_gateway() as gateway:
        tools = await gateway.list_tools()

    names = {tool.name for tool in tools}
    assert "search_incidents" in names
    assert "find_related_incidents" in names
    assert "execute_sql" not in names
