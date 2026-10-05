"""Reproducible, locally executed hybrid evaluation for SGCIU.

The citizen actor knows only a scenario's factual ledger and never receives the
gold labels.  SGCIU receives only the actor's natural-language messages.  This
keeps actor-generation cost and ground truth outside the measured application
interaction while retaining a realistic multi-turn intake journey.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

from openai import OpenAI, OpenAIError
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.intake import IntakeProvider
from app.config import Settings, get_settings
from app.models import AIInteractionTrace, ComplaintSubmission, IncidentClusterMember
from app.schemas import (
    ChatMessage,
    IntakeSubmissionRequest,
    InternalIntakeSubmissionRequest,
    StrictModel,
)
from app.services.intake import IntakeService
from app.services.semantic import SemanticIncidentService

LOCAL_TIMEZONE = ZoneInfo("America/Costa_Rica")
DATASET_VERSION = "hybrid-flores-v1"
SCENARIO_COUNT = 90
SCENARIO_START = datetime(2026, 1, 1, 8, 0, tzinfo=LOCAL_TIMEZONE)
SCENARIO_END = datetime(2026, 9, 7, 20, 0, tzinfo=LOCAL_TIMEZONE)

CATEGORIES = (
    "ruido",
    "vehiculo_sospechoso",
    "venta_drogas",
    "violencia",
    "robo",
    "vandalismo",
    "persona_sospechosa",
    "emergencia",
    "disturbio_publico",
    "basura_o_contaminacion",
    "alumbrado_publico",
    "obstruccion_via_publica",
    "animal_peligroso",
    "consumo_alcohol_drogas",
    "acoso_o_amenaza",
    "problema_transito",
    "otro",
)
DISTRICTS = ("San Joaquin", "Barrantes", "Llorente")
RELATIONS = ("vecino", "testigo", "victima", "comerciante", "otro")
PLACE_TYPES = ("establecimiento", "casa", "parque", "escuela", "otro")

INCIDENT_TEMPLATES: dict[str, str] = {
    "ruido": "música con parlantes y gritos a volumen alto durante la noche",
    "vehiculo_sospechoso": (
        "un automóvil oscuro sin placas visibles que dio vueltas despacio frente a varios locales "
        "cerrados"
    ),
    "venta_drogas": "intercambios rápidos de objetos pequeños y dinero entre varias personas",
    "violencia": "una agresión física entre dos personas que dejó a una de ellas golpeada",
    "robo": "una persona tomó una pertenencia ajena y salió corriendo",
    "vandalismo": "pintura y daños recientes en mobiliario de uso público",
    "persona_sospechosa": "una persona observando repetidamente entradas de viviendas y vehículos",
    "emergencia": "un cable eléctrico caído que produce chispas cerca de personas que pasan",
    "disturbio_publico": (
        "una discusión con gritos y empujones entre varias personas en la vía pública"
    ),
    "basura_o_contaminacion": (
        "bolsas de basura y residuos acumulados que bloquean parcialmente una cuneta"
    ),
    "alumbrado_publico": "una luminaria pública apagada que deja la calle muy oscura por la noche",
    "obstruccion_via_publica": "un camión estacionado que bloquea el paso de vehículos y peatones",
    "animal_peligroso": "un perro grande suelto que intentó morder a personas que caminaban",
    "consumo_alcohol_drogas": "varias personas consumiendo alcohol y sustancias en la acera",
    "acoso_o_amenaza": "una persona siguiendo y amenazando verbalmente a otra cerca de su vivienda",
    "problema_transito": "una colisión menor que dejó vehículos detenidos y una fila extensa",
    "otro": (
        "una situación inusual que afecta la convivencia y no encaja claramente en otra categoría"
    ),
}

DISTRICT_REFERENCES = {
    "San Joaquin": (
        "costado norte del parque central de San Joaquín",
        "100 metros sur de la Escuela Estados Unidos de América",
        "Calle Central, frente a la zona comercial de San Joaquín",
    ),
    "Barrantes": (
        "frente al salón comunal de Barrantes",
        "200 metros oeste de la iglesia de Barrantes",
        "calle principal de Barrantes, cerca de la plaza",
    ),
    "Llorente": (
        "frente al salón comunal de Llorente",
        "150 metros norte de la iglesia de Llorente",
        "costado este del parque de Llorente",
    ),
}

PERSONAS = (
    "persona vecina directa y concisa",
    "comerciante con prisa",
    "persona adulta mayor que usa referencias locales",
    "testigo nervioso que recuerda detalles por partes",
    "persona joven con redacción informal y algunas faltas leves",
    "persona cuidadosa que solo comparte lo que observó",
)


@dataclass(frozen=True, slots=True)
class HybridScenario:
    case_id: str
    persona: str
    channel: str
    facts: str
    expected_category: str
    expected_district: str
    expected_relation: str
    expected_place_type: str
    expected_address: str
    expected_event_at: datetime
    expected_temporal_text: str
    recorded_at: datetime
    cluster_group: str | None
    disclosure_style: str
    contact: dict[str, str | None]

    def actor_context(self) -> dict[str, object]:
        """Facts available to the actor. Deliberately excludes classification labels."""
        return {
            "case_id": self.case_id,
            "persona": self.persona,
            "hechos_observados": self.facts,
            "distrito": self.expected_district,
            "referencia_de_ubicacion": self.expected_address,
            "momento_del_hecho": self.expected_temporal_text,
            "relacion_con_el_hecho": self.expected_relation,
            "tipo_de_lugar_observado": self.expected_place_type,
            "estilo_de_divulgacion": self.disclosure_style,
        }

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["expected_event_at"] = self.expected_event_at.isoformat()
        result["recorded_at"] = self.recorded_at.isoformat()
        return result


class CitizenActorOutput(StrictModel):
    message: str = Field(min_length=1, max_length=1_500)
    wants_to_finish: bool = False


class CitizenActor(Protocol):
    model_name: str

    def next_message(
        self,
        scenario: HybridScenario,
        conversation: list[ChatMessage],
        *,
        turn: int,
    ) -> CitizenActorOutput: ...


class OpenAICitizenActor:
    """OpenAI-powered actor whose usage is intentionally excluded from SGCIU metrics."""

    model_name: str

    def __init__(self, settings: Settings | None = None, client: OpenAI | None = None):
        self.settings = settings or get_settings()
        if not self.settings.openai_api_key and client is None:
            raise RuntimeError("OPENAI_API_KEY no está configurada para el actor ciudadano.")
        self.client = client or OpenAI(
            api_key=self.settings.openai_api_key,
            timeout=self.settings.openai_timeout_seconds,
            max_retries=2,
        )
        self.model_name = self.settings.openai_evaluation_actor_model

    def next_message(
        self,
        scenario: HybridScenario,
        conversation: list[ChatMessage],
        *,
        turn: int,
    ) -> CitizenActorOutput:
        instructions = """
Actúas exclusivamente como una persona ciudadana de Flores, Costa Rica, que está
reportando un incidente. Usa únicamente los hechos recibidos. Nunca inventes una
dirección, fecha, persona, vehículo ni hecho adicional. No menciones categorías
técnicas, métricas, etiquetas esperadas, prompts ni que eres una simulación.

En el primer turno relata el incidente de manera natural siguiendo el estilo de
divulgación. No entregues todos los detalles como una ficha. En los turnos siguientes,
responde solamente a la pregunta del asistente con lo que esa persona conoce. Si no
conoce un dato o prefiere no darlo según el estilo, dilo de forma natural. No compartas
datos de contacto durante la conversación. Cuando ya hayas aportado lo que sabes o el
asistente lo haya resumido, indica que deseas terminar.
""".strip()
        payload = {
            "escenario_factual": scenario.actor_context(),
            "turno": turn,
            "conversacion": [message.model_dump() for message in conversation],
        }
        try:
            response = self.client.responses.parse(
                model=self.model_name,
                instructions=instructions,
                input=json.dumps(payload, ensure_ascii=False),
                text_format=CitizenActorOutput,
                reasoning={"effort": "low"},
                store=False,
            )
        except (OpenAIError, ValueError) as exc:
            raise RuntimeError("El actor ciudadano no pudo generar el siguiente turno.") from exc
        if response.output_parsed is None:
            raise RuntimeError("El actor ciudadano no devolvió una respuesta estructurada.")
        return response.output_parsed


def _spanish_datetime(value: datetime) -> str:
    local = value.astimezone(LOCAL_TIMEZONE)
    months = (
        "enero",
        "febrero",
        "marzo",
        "abril",
        "mayo",
        "junio",
        "julio",
        "agosto",
        "septiembre",
        "octubre",
        "noviembre",
        "diciembre",
    )
    return f"el {local.day} de {months[local.month - 1]} de {local.year} a las {local:%H:%M}"


def _event_time(index: int) -> datetime:
    digest = hashlib.sha256(f"hybrid-event-{index}".encode()).digest()
    span = int((SCENARIO_END - SCENARIO_START).total_seconds())
    return SCENARIO_START + timedelta(seconds=int.from_bytes(digest[:8], "big") % span)


def _recorded_time(event_at: datetime, index: int) -> datetime:
    lag_days = (0, 0, 1, 2, 4, 7, 14, 30, 45, 60)[index % 10]
    candidate = event_at + timedelta(days=lag_days, hours=index % 5)
    return min(candidate, SCENARIO_END)


def _contact(case_id: str, channel: str) -> dict[str, str | None]:
    if channel == "anonymous" or channel == "staff":
        return {"name": None, "identification": None, "email": None, "phone": None}
    values = {
        "name": f"Caso sintético {case_id}",
        "identification": f"EVAL-{case_id}",
        # example.com is a syntactically valid, reserved documentation domain.
        # Pydantic intentionally rejects the special-use .invalid TLD.
        "email": f"{case_id.casefold()}@example.com",
        "phone": f"+506 0000-{case_id[-4:]}",
    }
    if channel == "identified_partial":
        keep = ("name", "email") if int(case_id[-3:]) % 2 else ("name", "phone")
        return {key: value if key in keep else None for key, value in values.items()}
    return values


def _scenario_facts(category: str, address: str, temporal_text: str, variant: int) -> str:
    template = INCIDENT_TEMPLATES[category]
    openings = (
        "Quiero reportar",
        "Vi",
        "En mi barrio ocurrió",
        "Necesito avisar sobre",
        "Desde mi negocio noté",
    )
    return (
        f"{openings[variant % len(openings)]} {template} cerca de {address}; "
        f"fue {temporal_text}."
    )


def build_hybrid_scenarios() -> list[HybridScenario]:
    """Create 90 fixed gold scenarios: 12 three-member groups and 54 non-members."""
    scenarios: list[HybridScenario] = []
    channels = ["anonymous"] * 23 + ["identified_full"] * 31
    channels += ["identified_partial"] * 18 + ["staff"] * 18
    for index in range(SCENARIO_COUNT):
        grouped = index < 36
        group_index = index // 3 if grouped else None
        member_index = index % 3
        category = (
            CATEGORIES[(group_index * 2) % len(CATEGORIES)]
            if grouped
            else CATEGORIES[index % len(CATEGORIES)]
        )
        location_index = group_index if grouped else index
        district = DISTRICTS[location_index % len(DISTRICTS)]
        place_type = PLACE_TYPES[location_index % len(PLACE_TYPES)]
        address = DISTRICT_REFERENCES[district][location_index % 3]
        if grouped:
            event_at = SCENARIO_START + timedelta(days=group_index * 17 + member_index, hours=19)
            cluster_group = f"HCL-{group_index + 1:02d}"
        else:
            event_at = _event_time(index)
            cluster_group = None
            address = f"{address}, sector de referencia {index + 1}"
        temporal_text = _spanish_datetime(event_at)
        case_id = f"HYB-{index + 1:03d}"
        relation = RELATIONS[index % len(RELATIONS)]
        scenarios.append(
            HybridScenario(
                case_id=case_id,
                persona=PERSONAS[index % len(PERSONAS)],
                channel=channels[index],
                facts=_scenario_facts(category, address, temporal_text, index),
                expected_category=category,
                expected_district=district,
                expected_relation=relation,
                expected_place_type=place_type,
                expected_address=address,
                expected_event_at=event_at,
                expected_temporal_text=temporal_text,
                recorded_at=_recorded_time(event_at, index),
                cluster_group=cluster_group,
                disclosure_style=(
                    "incluye solo el hecho principal y responde los detalles cuando se le pregunten"
                    if index % 3
                    else "da una descripción fragmentada y admite no conocer detalles secundarios"
                ),
                contact=_contact(case_id, channels[index]),
            )
        )
    return scenarios


def scenario_dataset_hash(scenarios: list[HybridScenario]) -> str:
    payload = [scenario.to_dict() for scenario in scenarios]
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ranked = sorted(values)
    index = max(0, min(len(ranked) - 1, int(len(ranked) * percentile + 0.999999) - 1))
    return round(ranked[index], 2)


def _accuracy(results: list[bool]) -> float:
    return round(sum(results) / len(results), 4) if results else 0.0


def _cluster_metrics(db: Session, executions: list[dict[str, object]]) -> dict[str, object]:
    incidents = {
        int(execution["incident_id"]): execution
        for execution in executions
        if execution.get("incident_id") is not None
        and bool(execution.get("embedding", {}).get("success"))
    }
    expected_groups: dict[str, set[int]] = {}
    for incident_id, execution in incidents.items():
        group = execution.get("cluster_group")
        if isinstance(group, str):
            expected_groups.setdefault(group, set()).add(incident_id)
    expected_pairs = {
        tuple(sorted((left, right)))
        for members in expected_groups.values()
        for left in members
        for right in members
        if left < right
    }
    service = SemanticIncidentService(db)
    candidate_ids = set(incidents)
    actual_pairs: set[tuple[int, int]] = set()
    for incident_id in candidate_ids:
        incident = db.get(ComplaintSubmission, incident_id)
        if incident is None:
            continue
        for related in service.find_related(
            incident,
            top_k=None,
            minimum_score=service.settings.similarity_threshold,
            candidate_incident_ids=candidate_ids,
        ):
            actual_pairs.add(tuple(sorted((incident_id, related.incident.id))))
    true_positive = len(expected_pairs & actual_pairs)
    precision = true_positive / len(actual_pairs) if actual_pairs else 0.0
    recall = true_positive / len(expected_pairs) if expected_pairs else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "expected_pairs": len(expected_pairs),
        "predicted_pairs": len(actual_pairs),
        "true_positive_pairs": true_positive,
        "pairwise_precision": round(precision, 4),
        "pairwise_recall": round(recall, 4),
        "pairwise_f1": round(f1, 4),
    }


def _tag_execution(
    db: Session,
    incident: ComplaintSubmission,
    *,
    session_id: str,
    run_id: str,
    scenario: HybridScenario,
) -> list[AIInteractionTrace]:
    incident.created_at = scenario.recorded_at.astimezone(UTC)
    incident.analysis_metadata = {
        **(incident.analysis_metadata or {}),
        "synthetic": True,
        "evaluation_run_id": run_id,
        "evaluation_case_id": scenario.case_id,
        "evaluation_source": "hybrid_local_actor",
        "dataset_version": DATASET_VERSION,
    }
    traces = list(
        db.scalars(
            select(AIInteractionTrace)
            .where(AIInteractionTrace.session_id == session_id)
            .order_by(AIInteractionTrace.created_at)
        )
    )
    for trace in traces:
        trace.result_metadata = {
            **(trace.result_metadata or {}),
            "evaluation_run_id": run_id,
            "evaluation_case_id": scenario.case_id,
        }
    db.commit()
    return traces


def run_hybrid_evaluation(
    db: Session,
    *,
    actor: CitizenActor,
    intake_provider: IntakeProvider,
    run_id: str | None = None,
    max_turns: int = 5,
) -> dict[str, object]:
    """Execute all scenarios through IntakeService, excluding actor usage from results."""
    scenarios = build_hybrid_scenarios()
    run_id = run_id or f"hybrid-{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}"
    executions: list[dict[str, object]] = []
    indexed_incidents: list[ComplaintSubmission] = []
    started_at = datetime.now(UTC)
    semantic_service = SemanticIncidentService(db)
    for scenario in scenarios:
        service = IntakeService(db, provider=intake_provider, process_semantic=False)
        session = service.start(
            registration_mode="anonymous" if scenario.channel == "anonymous" else "complete"
        )
        response = service.to_response(session)
        actor_messages: list[str] = []
        forced_finish = False
        for turn in range(max_turns):
            actor_turn = actor.next_message(scenario, response.messages, turn=turn)
            actor_messages.append(actor_turn.message)
            response = service.add_user_message(session.id, actor_turn.message)
            if response.is_complete:
                break
            if actor_turn.wants_to_finish:
                response = service.add_user_message(
                    session.id,
                    "Eso es todo; deseo enviar la denuncia con la información disponible.",
                )
                forced_finish = True
                break
        if not response.is_complete:
            response = service.add_user_message(
                session.id,
                "Eso es todo; deseo enviar la denuncia con la información disponible.",
            )
            forced_finish = True
        if not response.is_complete:
            raise RuntimeError(f"El caso {scenario.case_id} no pudo finalizar el intake.")
        if scenario.channel == "staff":
            incident = service.submit_internal(
                session.id,
                InternalIntakeSubmissionRequest(
                    entered_by_badge=f"EVAL-{scenario.case_id}",
                    truth_confirmation=True,
                    data_usage_consent=True,
                ),
            )
        else:
            incident = service.submit(
                session.id,
                IntakeSubmissionRequest(
                    truth_confirmation=True,
                    data_usage_consent=True,
                    **scenario.contact,
                ),
            )
        embedding_started = time.perf_counter()
        embedding_error = None
        try:
            semantic_service.index_incident(incident)
            incident.analysis_metadata = {
                **(incident.analysis_metadata or {}),
                "embedding_status": "indexed",
            }
            db.commit()
            indexed_incidents.append(incident)
        except Exception as exc:
            embedding_error = type(exc).__name__
            incident.analysis_metadata = {
                **(incident.analysis_metadata or {}),
                "embedding_status": "pending",
            }
            db.commit()
        embedding_usage = semantic_service.provider.last_usage
        embedding = {
            "success": embedding_error is None,
            "error_type": embedding_error,
            "latency_ms": round((time.perf_counter() - embedding_started) * 1000, 2),
            "input_tokens": embedding_usage.input_tokens,
            "estimated_cost_usd": embedding_usage.estimated_cost_usd,
        }
        traces = _tag_execution(
            db,
            incident,
            session_id=session.id,
            run_id=run_id,
            scenario=scenario,
        )
        extracted = incident.ai_extracted_data or {}
        expected_event_date = scenario.expected_event_at.date().isoformat()
        actual_event_date = (
            incident.occurred_at.astimezone(LOCAL_TIMEZONE).date().isoformat()
            if incident.occurred_at
            else None
        )
        intake_usage = {
            "input_tokens": sum(trace.input_tokens for trace in traces),
            "output_tokens": sum(trace.output_tokens for trace in traces),
            "estimated_cost_usd": round(sum(trace.estimated_cost_usd for trace in traces), 8),
            "latency_ms": round(sum(trace.latency_ms for trace in traces), 2),
            "turns": len(traces),
        }
        executions.append(
            {
                "case_id": scenario.case_id,
                "incident_id": incident.id,
                "session_id": session.id,
                "trace_ids": [trace.trace_id for trace in traces],
                "channel": scenario.channel,
                "persona": scenario.persona,
                "cluster_group": scenario.cluster_group,
                "facts": scenario.facts,
                "actor_messages": actor_messages,
                "conversation": service.get(session.id).messages,
                "forced_finish": forced_finish,
                "expected": {
                    "category": scenario.expected_category,
                    "district": scenario.expected_district,
                    "relation": scenario.expected_relation,
                    "place_type": scenario.expected_place_type,
                    "event_date": expected_event_date,
                    "address": scenario.expected_address,
                },
                "actual": {
                    "category": extracted.get("categoria_preliminar"),
                    "district": extracted.get("distrito"),
                    "relation": extracted.get("relacion_incidente"),
                    "place_type": extracted.get("tipo_lugar"),
                    "event_date": actual_event_date,
                    "address": extracted.get("direccion_exacta"),
                    "summary": incident.ai_summary_text,
                    "temporal_precision": incident.occurred_at_precision,
                },
                "occurred_at": incident.occurred_at.isoformat() if incident.occurred_at else None,
                "recorded_at": incident.created_at.isoformat() if incident.created_at else None,
                "intake_usage": intake_usage,
                "embedding": embedding,
                "application_usage": {
                    "input_tokens": intake_usage["input_tokens"] + embedding["input_tokens"],
                    "output_tokens": intake_usage["output_tokens"],
                    "estimated_cost_usd": round(
                        intake_usage["estimated_cost_usd"] + embedding["estimated_cost_usd"],
                        8,
                    ),
                    "latency_ms": round(
                        intake_usage["latency_ms"] + embedding["latency_ms"],
                        2,
                    ),
                    "turns": intake_usage["turns"],
                },
            }
        )
    semantic_service.rebuild_clusters(indexed_incidents)
    cluster_by_incident = {
        incident_id: cluster_id
        for cluster_id, incident_id in db.execute(
            select(IncidentClusterMember.cluster_id, IncidentClusterMember.incident_id).where(
                IncidentClusterMember.incident_id.in_(
                    [int(execution["incident_id"]) for execution in executions]
                )
            )
        )
    }
    for execution in executions:
        execution["actual_cluster_id"] = cluster_by_incident.get(int(execution["incident_id"]))
    field_metrics = {
        field: _accuracy(
            [execution["expected"][field] == execution["actual"][field] for execution in executions]
        )
        for field in ("category", "district", "relation", "place_type", "event_date")
    }
    latencies = [
        float(execution["application_usage"]["latency_ms"]) for execution in executions
    ]
    total_input = sum(
        int(execution["application_usage"]["input_tokens"]) for execution in executions
    )
    total_output = sum(
        int(execution["application_usage"]["output_tokens"]) for execution in executions
    )
    total_cost = sum(
        float(execution["application_usage"]["estimated_cost_usd"]) for execution in executions
    )
    total_intake_cost = sum(
        float(execution["intake_usage"]["estimated_cost_usd"]) for execution in executions
    )
    total_embedding_cost = sum(
        float(execution["embedding"]["estimated_cost_usd"]) for execution in executions
    )
    report = {
        "run_id": run_id,
        "dataset_version": DATASET_VERSION,
        "dataset_sha256": scenario_dataset_hash(scenarios),
        "started_at": started_at.isoformat(),
        "completed_at": datetime.now(UTC).isoformat(),
        "execution_environment": "local_application",
        "actor_model": actor.model_name,
        "actor_cost_included_in_metrics": False,
        "scenarios": [scenario.to_dict() for scenario in scenarios],
        "executions": executions,
        "metrics": {
            "cases": len(executions),
            "field_accuracy": field_metrics,
            "completion_rate": _accuracy(
                [not execution["forced_finish"] for execution in executions]
            ),
            "forced_finish_rate": _accuracy(
                [bool(execution["forced_finish"]) for execution in executions]
            ),
            "latency_ms": {
                "average": round(sum(latencies) / len(latencies), 2),
                "p50": _percentile(latencies, 0.50),
                "p95": _percentile(latencies, 0.95),
            },
            "application_usage": {
                "input_tokens": total_input,
                "output_tokens": total_output,
                "estimated_cost_usd": round(total_cost, 8),
                "estimated_cost_per_case_usd": round(total_cost / len(executions), 8),
            },
            "intake_usage": {
                "estimated_cost_usd": round(total_intake_cost, 8),
            },
            "embedding": {
                "indexed": len(indexed_incidents),
                "failed": len(executions) - len(indexed_incidents),
                "estimated_cost_usd": round(total_embedding_cost, 8),
                "latency_ms": {
                    "average": round(
                        sum(float(execution["embedding"]["latency_ms"]) for execution in executions)
                        / len(executions),
                        2,
                    ),
                    "p50": _percentile(
                        [float(execution["embedding"]["latency_ms"]) for execution in executions],
                        0.50,
                    ),
                    "p95": _percentile(
                        [float(execution["embedding"]["latency_ms"]) for execution in executions],
                        0.95,
                    ),
                },
            },
            "clustering": _cluster_metrics(db, executions),
        },
    }
    return report


def write_report(path, report: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
