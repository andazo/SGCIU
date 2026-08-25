from __future__ import annotations

import json
import os
import sys
import uuid
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from sqlalchemy.orm import Session

from app.models import AuditEvent
from app.tools.incidents import build_incident_tool_registry
from app.tools.registry import ToolRegistry


@dataclass(frozen=True, slots=True)
class GatewayTool:
    name: str
    description: str
    input_schema: dict[str, object]


class ToolGateway(ABC):
    @abstractmethod
    async def list_tools(self) -> list[GatewayTool]: ...

    @abstractmethod
    async def call_tool(
        self,
        name: str,
        arguments: dict[str, object],
        *,
        trace_id: str | None = None,
    ) -> dict[str, object]: ...


class LocalToolGateway(ToolGateway):
    def __init__(
        self,
        db: Session,
        *,
        actor_role: str = "admin",
        registry: ToolRegistry | None = None,
    ):
        self.db = db
        self.actor_role = actor_role
        self.registry = registry or build_incident_tool_registry()

    async def list_tools(self) -> list[GatewayTool]:
        return [
            GatewayTool(
                name=definition.name,
                description=definition.description,
                input_schema=definition.json_schema(),
            )
            for definition in self.registry.list(self.actor_role)
        ]

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, object],
        *,
        trace_id: str | None = None,
    ) -> dict[str, object]:
        result = self.registry.call(self.db, name, arguments, actor_role=self.actor_role)
        self.db.add(
            AuditEvent(
                trace_id=trace_id or str(uuid.uuid4()),
                actor_role=self.actor_role,
                action=f"tool:{name}",
                resource_type="agent_tool",
                details={"argument_keys": sorted(arguments), "success": True},
            )
        )
        self.db.commit()
        return result


class MCPToolGateway(ToolGateway):
    def __init__(self, session: ClientSession):
        self.session = session

    async def list_tools(self) -> list[GatewayTool]:
        response = await self.session.list_tools()
        return [
            GatewayTool(
                name=tool.name,
                description=tool.description or "",
                input_schema=tool.inputSchema,
            )
            for tool in response.tools
        ]

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, object],
        *,
        trace_id: str | None = None,
    ) -> dict[str, object]:
        response = await self.session.call_tool(name, arguments)
        if response.isError:
            raise RuntimeError(f"MCP tool failed: {name}")
        if response.structuredContent:
            structured = dict(response.structuredContent)
            wrapped = structured.get("result")
            if len(structured) == 1 and isinstance(wrapped, str):
                parsed = json.loads(wrapped)
                return parsed if isinstance(parsed, dict) else {"result": parsed}
            return structured
        text_parts = [item.text for item in response.content if hasattr(item, "text")]
        if not text_parts:
            return {}
        parsed = json.loads("".join(text_parts))
        return parsed if isinstance(parsed, dict) else {"result": parsed}


@asynccontextmanager
async def connect_mcp_gateway() -> AsyncIterator[MCPToolGateway]:
    backend_root = Path(__file__).resolve().parents[2]
    environment = {**os.environ, "PYTHONPATH": str(backend_root)}
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "app.mcp_server"],
        env=environment,
    )
    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            yield MCPToolGateway(session)
