from __future__ import annotations

import json
import logging
import re
import time
import uuid

from openai import AsyncOpenAI

from app.agents.gateway import GatewayTool, ToolGateway
from app.config import Settings, get_settings
from app.schemas import OperationalQueryResponse, ToolExecutionTrace

logger = logging.getLogger(__name__)
AGENT_PROMPT_VERSION = "operational-react-v1"
SYSTEM_PROMPT = """
Eres un asistente operativo para personal autorizado de la Policía Municipal de
Flores. Responde preguntas exclusivamente a partir de las herramientas SGCIU.

Usa herramientas para obtener hechos, conteos y relaciones; nunca inventes
incidentes ni realices cálculos sobre datos que no recuperaste. Las agrupaciones
y similitudes son candidatas y requieren interpretación humana. No reveles datos
de contacto ni solicites SQL. Solicita revisión humana cuando una acción o dato
sea sensible. Responde en español y cita los IDs de incidentes utilizados.
""".strip()


def _strict_tool_schema(schema: dict[str, object]) -> dict[str, object]:
    def visit(node: object) -> None:
        if isinstance(node, dict):
            properties = node.get("properties")
            if isinstance(properties, dict):
                node["additionalProperties"] = False
                node["required"] = list(properties)
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(schema)
    return schema


def _result_count(result: dict[str, object]) -> int | None:
    for key in ("returned", "total"):
        value = result.get(key)
        if isinstance(value, int):
            return value
    for key in ("incidents", "related", "groups", "members"):
        value = result.get(key)
        if isinstance(value, list):
            return len(value)
    return None


def _incident_ids(value: object) -> set[int]:
    found: set[int] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "incident_id" and isinstance(child, int):
                found.add(child)
            else:
                found.update(_incident_ids(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_incident_ids(child))
    return found


def _trace_arguments(arguments: dict[str, object]) -> dict[str, object]:
    sensitive_keys = {"reason", "description", "query", "text"}
    return {
        key: "[REDACTED]" if key in sensitive_keys else value for key, value in arguments.items()
    }


class OperationalAgent:
    def __init__(
        self,
        gateway: ToolGateway,
        settings: Settings | None = None,
    ):
        self.gateway = gateway
        self.settings = settings or get_settings()

    async def run(self, query: str) -> OperationalQueryResponse:
        trace_id = str(uuid.uuid4())
        started = time.perf_counter()
        if self.settings.llm_provider == "mock":
            response = await self._run_deterministic(query, trace_id)
        else:
            response = await self._run_openai(query, trace_id)
        logger.info(
            "Operational agent completed",
            extra={
                "feature": "operational_agent",
                "model": response.model_name,
                "prompt_version": AGENT_PROMPT_VERSION,
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                "tool_steps": len(response.steps),
            },
        )
        return response

    async def _run_openai(self, query: str, trace_id: str) -> OperationalQueryResponse:
        if not self.settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY no está configurada para el agente operativo.")
        client = AsyncOpenAI(api_key=self.settings.openai_api_key)
        gateway_tools = await self.gateway.list_tools()
        tools = [self._openai_tool(tool) for tool in gateway_tools]
        response = await client.responses.create(
            model=self.settings.openai_model,
            instructions=SYSTEM_PROMPT,
            input=query,
            tools=tools,
        )
        steps: list[ToolExecutionTrace] = []
        citations: set[int] = set()
        for step_number in range(1, self.settings.agent_max_steps + 1):
            calls = [item for item in response.output if item.type == "function_call"]
            if not calls:
                return OperationalQueryResponse(
                    answer=response.output_text,
                    incident_citations=sorted(citations),
                    trace_id=trace_id,
                    steps=steps,
                    model_name=self.settings.openai_model,
                    prompt_version=AGENT_PROMPT_VERSION,
                )
            outputs: list[dict[str, object]] = []
            for call in calls:
                arguments = json.loads(call.arguments)
                tool_started = time.perf_counter()
                try:
                    result = await self.gateway.call_tool(call.name, arguments, trace_id=trace_id)
                    success = True
                    error_type = None
                    citations.update(_incident_ids(result))
                except Exception as exc:
                    result = {"error": "La herramienta no pudo completar la operación."}
                    success = False
                    error_type = type(exc).__name__
                steps.append(
                    ToolExecutionTrace(
                        step=step_number,
                        tool_name=call.name,
                        arguments=_trace_arguments(arguments),
                        success=success,
                        result_count=_result_count(result),
                        latency_ms=round((time.perf_counter() - tool_started) * 1000, 2),
                        error_type=error_type,
                    )
                )
                outputs.append(
                    {
                        "type": "function_call_output",
                        "call_id": call.call_id,
                        "output": json.dumps(result, ensure_ascii=False, default=str),
                    }
                )
            response = await client.responses.create(
                model=self.settings.openai_model,
                previous_response_id=response.id,
                input=outputs,
                tools=tools,
            )
        return OperationalQueryResponse(
            answer=(
                "No fue posible completar la consulta dentro del límite seguro de pasos. "
                "Reformule la pregunta o consulte los incidentes directamente."
            ),
            incident_citations=sorted(citations),
            trace_id=trace_id,
            steps=steps,
            model_name=self.settings.openai_model,
            prompt_version=AGENT_PROMPT_VERSION,
            requires_human_review=True,
        )

    async def _run_deterministic(self, query: str, trace_id: str) -> OperationalQueryResponse:
        normalized = query.casefold()
        incident_match = re.search(r"(?:incidente|id)\s*#?\s*(\d+)", normalized)
        district = next(
            (
                name
                for name in ("San Joaquin", "Barrantes", "Llorente")
                if name.casefold() in normalized
            ),
            None,
        )
        category_map = {
            "ruido": "ruido",
            "robo": "robo",
            "violencia": "violencia",
            "vandalismo": "vandalismo",
            "drogas": "venta_drogas",
            "tránsito": "problema_transito",
        }
        category = next((value for key, value in category_map.items() if key in normalized), None)
        if incident_match and any(word in normalized for word in ("similar", "relacionado")):
            tool_name = "find_related_incidents"
            arguments: dict[str, object] = {
                "incident_id": int(incident_match.group(1)),
                "top_k": 5,
            }
        elif incident_match:
            tool_name = "get_incident"
            arguments = {"incident_id": int(incident_match.group(1))}
        elif any(word in normalized for word in ("más frecuente", "más común", "cuánt")):
            tool_name = "aggregate_incidents"
            arguments = {
                "group_by": "categoria_preliminar",
                "district": district,
                "category": category,
            }
        else:
            tool_name = "search_incidents"
            arguments = {"district": district, "category": category, "limit": 20}
        tool_started = time.perf_counter()
        result = await self.gateway.call_tool(tool_name, arguments, trace_id=trace_id)
        step = ToolExecutionTrace(
            step=1,
            tool_name=tool_name,
            arguments=_trace_arguments(arguments),
            success=True,
            result_count=_result_count(result),
            latency_ms=round((time.perf_counter() - tool_started) * 1000, 2),
        )
        return OperationalQueryResponse(
            answer=self._deterministic_answer(tool_name, result),
            incident_citations=sorted(_incident_ids(result)),
            trace_id=trace_id,
            steps=[step],
            model_name="deterministic-react-demo",
            prompt_version=AGENT_PROMPT_VERSION,
        )

    @staticmethod
    def _openai_tool(tool: GatewayTool) -> dict[str, object]:
        return {
            "type": "function",
            "name": tool.name,
            "description": tool.description,
            "parameters": _strict_tool_schema(tool.input_schema),
            "strict": True,
        }

    @staticmethod
    def _deterministic_answer(tool_name: str, result: dict[str, object]) -> str:
        if tool_name == "aggregate_incidents":
            groups = result.get("groups") or []
            if not groups:
                return "No se encontraron incidentes para los filtros indicados."
            leading = groups[0]
            return (
                f"Se encontraron {result.get('total', 0)} incidentes. "
                f"El grupo principal es {leading['value']} con {leading['count']} reportes."
            )
        if tool_name == "find_related_incidents":
            related = result.get("related") or []
            return (
                f"Se encontraron {len(related)} posibles incidentes relacionados. "
                "Las coincidencias son candidatas y deben ser revisadas por un oficial."
            )
        if tool_name == "get_incident":
            if not result.get("found"):
                return "No se encontró el incidente solicitado."
            incident = result["incident"]
            return (
                f"El incidente {incident['incident_id']} está clasificado como "
                f"{incident['category']} en {incident['district']}."
            )
        return f"Se encontraron {result.get('total', 0)} incidentes para la consulta."
