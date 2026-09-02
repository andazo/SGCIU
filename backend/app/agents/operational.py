from __future__ import annotations

import json
import logging
import time
import uuid

from openai import AsyncOpenAI

from app.agents.gateway import GatewayTool, ToolGateway
from app.config import Settings, get_settings
from app.costs import estimate_llm_cost
from app.schemas import ChatMessage, ModelUsage, OperationalQueryResponse, ToolExecutionTrace

logger = logging.getLogger(__name__)
AGENT_PROMPT_VERSION = "operational-react-v5"
SYSTEM_PROMPT = """
Eres un asistente operativo para personal autorizado de la Policía Municipal de
Flores. Responde preguntas exclusivamente a partir de las herramientas SGCIU.

Usa herramientas para obtener hechos, conteos y relaciones; nunca inventes
incidentes ni realices cálculos sobre datos que no recuperaste. Las agrupaciones
y similitudes son candidatas y requieren interpretación humana. No reveles datos
de contacto ni solicites SQL. Solicita revisión humana cuando una acción o dato
sea sensible. Responde en español y cita los IDs de incidentes utilizados.
Usa frases cortas y una estructura fácil de leer: coloca cada filtro o dato en una
línea separada con guion, y resalta los valores importantes con doble asterisco.
Para cualquier pregunta de cantidad, frecuencia o comparación usa siempre
aggregate_incidents; no cuentes la lista limitada de search_incidents ni calcules
totales a partir del texto de la conversación. Devuelve el total y los filtros
normalizados que entregue la herramienta.
Si existe historial de la conversación, úsalo únicamente para resolver referencias
como "ese distrito" o "los anteriores"; verifica siempre los hechos y conteos actuales
con una herramienta en cada respuesta. Un resultado vacío significa cero sólo después
de que la herramienta haya aplicado filtros normalizados y debes explicitar dichos filtros.
Para buscar por fecha usa created_from y created_to en formato YYYY-MM-DD. Esas fechas
corresponden a created_at, el momento en que SGCIU registró el incidente; no confundas
esa fecha con fecha_hora_aproximada, que actualmente es evidencia textual del momento
del hecho y no permite una comparación cronológica exacta.
Para consultas sobre normativa, competencias o protocolos usa search_legal_sources,
limítate a sus fragmentos y cita los identificadores [F#], el documento y la página
PDF exacta. Aclara que la orientación no sustituye criterio jurídico institucional.
Clasifica cada conclusión jurídica como "Obligación legal", "Facultad municipal" o
"Procedimiento recomendado", respetando allowed_classifications de cada fuente. No
atribuyas a la Policía Municipal una facultad de Fuerza Pública, Poder Judicial u otra
institución. Los protocolos externos son referencias operativas cuya aplicabilidad local
debe confirmarse.
Cuando la consulta mencione casos de prueba, ficticios o sintéticos, utiliza el
argumento synthetic_only=true de la herramienta correspondiente; nunca lo
interpretes como una categoría de incidente.
Ejemplo: para "incidentes sintéticos en cada distrito", llama a
aggregate_incidents con group_by="distrito", district=null, category=null y
synthetic_only=true.
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


def _legal_source_ids(value: object) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "source_id" and isinstance(child, str):
                found.add(child)
            else:
                found.update(_legal_source_ids(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_legal_source_ids(child))
    return found


def _legal_source_records(value: object) -> dict[str, dict[str, object]]:
    found: dict[str, dict[str, object]] = {}
    if isinstance(value, dict):
        source_id = value.get("source_id")
        if isinstance(source_id, str):
            found[source_id] = value
        for child in value.values():
            found.update(_legal_source_records(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_legal_source_records(child))
    return found


def _append_legal_source_details(
    answer: str,
    sources: dict[str, dict[str, object]],
) -> str:
    if not sources:
        return answer
    labels = {
        "legal_obligation": "obligación legal",
        "municipal_authority": "facultad municipal",
        "recommended_procedure": "procedimiento recomendado",
    }
    lines = ["Fuentes normativas recuperadas:"]
    for source_id in sorted(
        sources,
        key=lambda value: (
            (0, int(value[1:]))
            if value.startswith("F") and value[1:].isdigit()
            else (1, value)
        ),
    ):
        source = sources[source_id]
        allowed = ", ".join(
            labels.get(value, str(value))
            for value in source.get("allowed_classifications", [])
        )
        articles = ", ".join(source.get("article_references", []))
        locator = f"página PDF {source.get('pdf_page')}"
        if articles:
            locator += f", {articles}"
        line = f"- [{source_id}] {source.get('document_title')} — {locator}"
        if allowed:
            line += f"; puede respaldar: {allowed}"
        lines.append(line)
    return f"{answer.rstrip()}\n\n" + "\n".join(lines)


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
        client: AsyncOpenAI | None = None,
    ):
        self.gateway = gateway
        self.settings = settings or get_settings()
        self.client = client

    async def run(
        self,
        query: str,
        *,
        history: list[ChatMessage] | None = None,
    ) -> OperationalQueryResponse:
        trace_id = str(uuid.uuid4())
        started = time.perf_counter()
        response = await self._run_openai(query, trace_id, history=history)
        logger.info(
            "Operational agent completed",
            extra={
                "feature": "operational_agent",
                "model": response.model_name,
                "prompt_version": AGENT_PROMPT_VERSION,
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                "tool_steps": len(response.steps),
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
                "estimated_cost_usd": response.usage.estimated_cost_usd,
            },
        )
        return response

    async def _run_openai(
        self,
        query: str,
        trace_id: str,
        *,
        history: list[ChatMessage] | None = None,
    ) -> OperationalQueryResponse:
        if not self.settings.openai_api_key and self.client is None:
            raise RuntimeError("OPENAI_API_KEY no está configurada para el agente operativo.")
        client = self.client or AsyncOpenAI(
            api_key=self.settings.openai_api_key,
            timeout=self.settings.openai_timeout_seconds,
            max_retries=2,
        )
        gateway_tools = await self.gateway.list_tools()
        tools = [self._openai_tool(tool) for tool in gateway_tools]
        conversation = [
            message.model_dump() for message in (history or [])[-12:]
        ]
        conversation.append({"role": "user", "content": query})
        response = await client.responses.create(
            model=self.settings.openai_model,
            instructions=SYSTEM_PROMPT,
            input=conversation,
            tools=tools,
        )
        input_tokens, output_tokens = self._response_usage(response)
        steps: list[ToolExecutionTrace] = []
        citations: set[int] = set()
        legal_citations: set[str] = set()
        legal_sources: dict[str, dict[str, object]] = {}
        for step_number in range(1, self.settings.agent_max_steps + 1):
            calls = [item for item in response.output if item.type == "function_call"]
            if not calls:
                return OperationalQueryResponse(
                    answer=_append_legal_source_details(response.output_text, legal_sources),
                    incident_citations=sorted(citations),
                    legal_citations=sorted(legal_citations),
                    trace_id=trace_id,
                    steps=steps,
                    model_name=self.settings.openai_model,
                    prompt_version=AGENT_PROMPT_VERSION,
                    usage=self._model_usage(input_tokens, output_tokens),
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
                    legal_citations.update(_legal_source_ids(result))
                    legal_sources.update(_legal_source_records(result))
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
                instructions=SYSTEM_PROMPT,
                tools=tools,
            )
            next_input, next_output = self._response_usage(response)
            input_tokens += next_input
            output_tokens += next_output
        return OperationalQueryResponse(
            answer=(
                "No fue posible completar la consulta dentro del límite seguro de pasos. "
                "Reformule la pregunta o consulte los incidentes directamente."
            ),
            incident_citations=sorted(citations),
            legal_citations=sorted(legal_citations),
            trace_id=trace_id,
            steps=steps,
            model_name=self.settings.openai_model,
            prompt_version=AGENT_PROMPT_VERSION,
            requires_human_review=True,
            usage=self._model_usage(input_tokens, output_tokens),
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
    def _response_usage(response: object) -> tuple[int, int]:
        usage = getattr(response, "usage", None)
        return (
            int(getattr(usage, "input_tokens", 0) or 0),
            int(getattr(usage, "output_tokens", 0) or 0),
        )

    def _model_usage(self, input_tokens: int, output_tokens: int) -> ModelUsage:
        return ModelUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost_usd=estimate_llm_cost(input_tokens, output_tokens, self.settings),
        )
