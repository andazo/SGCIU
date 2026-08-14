from __future__ import annotations

import json
import uuid

from mcp.server.fastmcp import FastMCP

from app.db import SessionLocal
from app.models import AuditEvent
from app.tools.incidents import build_incident_tool_registry

mcp = FastMCP("sgciu-incident-intelligence")
registry = build_incident_tool_registry()


def _execute(name: str, arguments: dict[str, object]) -> str:
    with SessionLocal() as db:
        result = registry.call(db, name, arguments, actor_role="admin")
        db.add(
            AuditEvent(
                trace_id=str(uuid.uuid4()),
                actor_role="admin",
                action=f"mcp_tool:{name}",
                resource_type="mcp_tool",
                details={"argument_keys": sorted(arguments), "success": True},
            )
        )
        db.commit()
        return json.dumps(result, ensure_ascii=False, default=str)


@mcp.tool()
def get_incident(incident_id: int) -> str:
    """Obtiene información operativa sanitizada de un incidente por ID."""
    return _execute("get_incident", {"incident_id": incident_id})


@mcp.tool()
def search_incidents(
    district: str | None = None,
    category: str | None = None,
    limit: int = 20,
) -> str:
    """Busca incidentes por distrito o categoría sin devolver datos de contacto."""
    return _execute(
        "search_incidents",
        {"district": district, "category": category, "limit": limit},
    )


@mcp.tool()
def aggregate_incidents(
    group_by: str,
    district: str | None = None,
    category: str | None = None,
) -> str:
    """Agrupa y cuenta incidentes por categoria_preliminar o distrito."""
    return _execute(
        "aggregate_incidents",
        {"group_by": group_by, "district": district, "category": category},
    )


@mcp.tool()
def find_related_incidents(incident_id: int, top_k: int = 5) -> str:
    """Busca posibles incidentes relacionados mediante similitud híbrida."""
    return _execute(
        "find_related_incidents",
        {"incident_id": incident_id, "top_k": top_k},
    )


@mcp.tool()
def get_incident_cluster(cluster_id: int) -> str:
    """Consulta un cluster candidato y sus incidentes miembros."""
    return _execute("get_incident_cluster", {"cluster_id": cluster_id})


@mcp.tool()
def request_human_review(incident_id: int, reason: str) -> str:
    """Solicita revisión humana explícita de un incidente; no modifica su clasificación."""
    return _execute(
        "request_human_review",
        {"incident_id": incident_id, "reason": reason},
    )


@mcp.resource("sgciu://capabilities")
def capabilities() -> str:
    """Describe las capacidades y límites del servidor MCP de SGCIU."""
    return json.dumps(
        {
            "server": "sgciu-incident-intelligence",
            "scope": "incidentes urbanos y clusters candidatos",
            "pii": "Los tools no devuelven nombre, correo ni teléfono.",
            "limitations": [
                "No expone SQL arbitrario.",
                "No determina culpabilidad.",
                "Las similitudes requieren supervisión humana.",
            ],
        },
        ensure_ascii=False,
    )


if __name__ == "__main__":
    mcp.run()
