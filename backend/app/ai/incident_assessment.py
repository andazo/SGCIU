from __future__ import annotations

import json
import logging
import re
import time
from abc import ABC, abstractmethod
from typing import Literal

from openai import OpenAI, OpenAIError
from pydantic import Field, model_validator

from app.config import Settings, get_settings
from app.costs import estimate_llm_cost
from app.schemas import ComplaintExtractedData, ReviewActionCode, ReviewType, StrictModel

logger = logging.getLogger(__name__)
ASSESSMENT_PROMPT_VERSION = "incident-assessment-v1"

SYSTEM_PROMPT = """
Eres un analista de apoyo para la Policía Municipal de Flores, Costa Rica. SGCIU
registra incidentes municipales y no es un servicio de emergencias ni garantiza
respuesta inmediata.

Analiza únicamente los datos proporcionados y produce dos decisiones independientes:

1. RESALTADO OPERATIVO: un hecho ya ocurrido o sin peligro de vida actual que merece
atención más pronta o precauciones especiales, por ejemplo violencia pasada, robo
violento, posible arma no confirmada, sonidos similares a disparos ya finalizados,
acoso reiterado o un patrón de riesgo. No conviertas una emergencia activa en una
promesa de respuesta municipal; marca possible_emergency para que el sistema mantenga
la orientación al 9-1-1.

2. REVISIÓN DE CALIDAD: información incompleta, contradictoria, semánticamente poco
clara, difícil de ubicar, posiblemente duplicada o sensible. Una emergencia no es por
sí sola una razón de revisión de calidad. Si se proporciona una razón previa de calidad,
la revisión es obligatoria y debes incorporarla.

El resumen debe distinguir hechos reportados, datos no confirmados y recomendaciones.
No determines culpabilidad, no inventes detalles y no incluyas nombres, teléfonos,
correos ni identificaciones. Usa contact_available solo para decidir si recomendar
contactar a la persona. Las acciones deben ser concretas y usar exclusivamente los
códigos permitidos por el esquema.
""".strip()


def _sanitized_incident_payload(data: ComplaintExtractedData) -> dict[str, object]:
    payload = data.model_dump()
    entities = payload.get("entities") or {}
    people = [str(person) for person in entities.get("people", [])]
    description = str(payload.get("descripcion_detallada") or "")
    for person in sorted(people, key=len, reverse=True):
        if person.strip():
            description = re.sub(re.escape(person), "[PERSONA]", description, flags=re.I)
    description = re.sub(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", "[CORREO]", description)
    description = re.sub(
        r"(?<!\d)(?:\+?506[ -]?)?\d{4}[ -]?\d{4}(?!\d)",
        "[TELÉFONO]",
        description,
    )
    payload["descripcion_detallada"] = description
    entities["people"] = []
    entities["evidence"] = [
        item
        for item in entities.get("evidence", [])
        if str(item.get("entity_type", "")).casefold() not in {"person", "persona"}
    ]
    payload["entities"] = entities
    return payload


class RecommendedAction(StrictModel):
    code: ReviewActionCode
    rationale: str = Field(min_length=5, max_length=500)


class HighlightAssessment(StrictModel):
    required: bool
    attention_level: Literal["prompt", "priority"] | None = None
    reasons: list[str] = Field(default_factory=list)
    operational_summary: str | None = None
    recommended_precautions: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def required_highlights_need_details(self):
        if self.required and (not self.attention_level or not self.operational_summary):
            raise ValueError("Un resaltado requiere nivel de atención y resumen.")
        return self


class QualityReviewAssessment(StrictModel):
    required: bool
    review_type: ReviewType | None = None
    issues: list[str] = Field(default_factory=list)
    admin_summary: str | None = None
    recommended_actions: list[RecommendedAction] = Field(default_factory=list)

    @model_validator(mode="after")
    def required_reviews_need_details(self):
        if self.required and (not self.review_type or not self.admin_summary):
            raise ValueError("Una revisión requiere tipo y resumen administrativo.")
        return self


class IncidentAssessment(StrictModel):
    possible_emergency: bool
    emergency_reason: str | None = None
    highlight: HighlightAssessment
    quality_review: QualityReviewAssessment


class IncidentAssessmentProvider(ABC):
    model_name: str

    @abstractmethod
    def assess(
        self,
        data: ComplaintExtractedData,
        *,
        incident_summary: str | None,
        initial_quality_reason: str | None,
        contact_available: bool,
    ) -> IncidentAssessment: ...


class OpenAIIncidentAssessmentProvider(IncidentAssessmentProvider):
    def __init__(self, settings: Settings, client: OpenAI | None = None):
        if not settings.openai_api_key and client is None:
            raise RuntimeError("OPENAI_API_KEY no está configurada para analizar incidentes.")
        self.client = client or OpenAI(
            api_key=settings.openai_api_key,
            timeout=settings.openai_timeout_seconds,
            max_retries=2,
        )
        self.settings = settings
        self.model_name = settings.openai_model

    def assess(
        self,
        data: ComplaintExtractedData,
        *,
        incident_summary: str | None,
        initial_quality_reason: str | None,
        contact_available: bool,
    ) -> IncidentAssessment:
        payload = {
            "incident": _sanitized_incident_payload(data),
            "initial_quality_reason": initial_quality_reason,
            "contact_available": contact_available,
        }
        started = time.perf_counter()
        try:
            response = self.client.responses.parse(
                model=self.model_name,
                instructions=SYSTEM_PROMPT,
                input=json.dumps(payload, ensure_ascii=False),
                text_format=IncidentAssessment,
                reasoning={"effort": "low"},
                store=False,
            )
        except (OpenAIError, ValueError) as exc:
            raise RuntimeError("No se pudo generar el análisis administrativo con OpenAI.") from exc
        assessment = response.output_parsed
        if assessment is None:
            raise RuntimeError("OpenAI no devolvió un análisis administrativo válido.")
        usage = getattr(response, "usage", None)
        input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        logger.info(
            "Incident administrative assessment completed",
            extra={
                "feature": "incident_assessment",
                "model": self.model_name,
                "prompt_version": ASSESSMENT_PROMPT_VERSION,
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "estimated_cost_usd": estimate_llm_cost(input_tokens, output_tokens, self.settings),
            },
        )
        return assessment


def get_incident_assessment_provider(
    settings: Settings | None = None,
) -> IncidentAssessmentProvider:
    return OpenAIIncidentAssessmentProvider(settings or get_settings())
