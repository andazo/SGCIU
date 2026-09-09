from __future__ import annotations

import json
import uuid
from datetime import date

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
    synthetic_only: bool | None = None,
    created_from: date | None = None,
    created_to: date | None = None,
    limit: int = 20,
    offset: int = 0,
    date_basis: str = "registration",
) -> str:
    """Busca incidentes por filtros operativos y fecha de registro, sin datos de contacto."""
    return _execute(
        "search_incidents",
        {
            "district": district,
            "category": category,
            "synthetic_only": synthetic_only,
            "created_from": created_from,
            "created_to": created_to,
            "limit": limit,
            "offset": offset,
            "date_basis": date_basis,
        },
    )


@mcp.tool()
def aggregate_incidents(
    group_by: str,
    district: str | None = None,
    category: str | None = None,
    synthetic_only: bool | None = None,
    created_from: date | None = None,
    created_to: date | None = None,
    date_basis: str = "registration",
) -> str:
    """Agrupa y cuenta incidentes por categoria_preliminar o distrito."""
    return _execute(
        "aggregate_incidents",
        {
            "group_by": group_by,
            "district": district,
            "category": category,
            "synthetic_only": synthetic_only,
            "created_from": created_from,
            "created_to": created_to,
            "date_basis": date_basis,
        },
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
def get_recurrent_patterns(window_days: int = 30) -> str:
    """Obtiene patrones recurrentes proactivos dentro de una ventana configurable."""
    return _execute("get_recurrent_patterns", {"window_days": window_days})


@mcp.tool()
def search_legal_sources(
    query: str,
    document_keys: list[str] | None = None,
    top_k: int = 8,
) -> str:
    """Recupera normativa con página exacta y clasificación jurídica permitida."""
    return _execute(
        "search_legal_sources",
        {"query": query, "document_keys": document_keys, "top_k": top_k},
    )


@mcp.tool()
def get_legal_corpus_status() -> str:
    """Informa la cobertura y cantidad de embeddings del corpus normativo."""
    return _execute("get_legal_corpus_status", {})


@mcp.resource("sgciu://capabilities")
def capabilities() -> str:
    """Describe las capacidades y límites del servidor MCP de SGCIU."""
    return json.dumps(
        {
            "server": "sgciu-incident-intelligence",
            "scope": (
                "incidentes urbanos, clusters candidatos, patrones recurrentes y corpus normativo"
            ),
            "pii": "Los tools no devuelven nombre, correo ni teléfono.",
            "limitations": [
                "No expone SQL arbitrario.",
                "No determina culpabilidad.",
                "Las similitudes requieren supervisión humana.",
                "Las respuestas normativas no sustituyen criterio jurídico institucional.",
            ],
        },
        ensure_ascii=False,
    )


if __name__ == "__main__":
    mcp.run()
