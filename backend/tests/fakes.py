from __future__ import annotations

import hashlib
import math
from collections import deque

from app.ai.incident_assessment import (
    HighlightAssessment,
    IncidentAssessment,
    IncidentAssessmentProvider,
    QualityReviewAssessment,
    RecommendedAction,
)
from app.ai.intake import DESIRED_FIELDS, IntakeProvider, actionable_missing_fields
from app.schemas import (
    ChatMessage,
    ComplaintExtractedData,
    ComplaintIntakeChatResponse,
    IntakeFieldObservation,
)


def extracted_data(**values: object) -> ComplaintExtractedData:
    data = ComplaintExtractedData.model_validate(values)
    for field in DESIRED_FIELDS:
        value = getattr(data, field)
        if value is not None:
            observation = IntakeFieldObservation(
                status="known",
                confidence=0.9,
                evidence=str(value),
            )
            setattr(data.field_states, field, observation)
            setattr(data.confidence_by_field, field, 0.9)
    return data


def intake_response(
    data: ComplaintExtractedData,
    *,
    assistant_message: str = "Gracias. Revise la información recopilada.",
    is_complete: bool = True,
    user_wants_to_finish: bool = False,
    completion_reason: str | None = None,
    requires_human_review: bool = False,
    review_reason: str | None = None,
    emergency_guidance: bool = False,
) -> ComplaintIntakeChatResponse:
    reason = completion_reason or ("all_fields_resolved" if is_complete else "needs_follow_up")
    return ComplaintIntakeChatResponse(
        assistant_message=assistant_message,
        is_complete=is_complete,
        missing_fields=actionable_missing_fields(data),
        extracted_data=data,
        summary_text="Resumen institucional de prueba." if is_complete else None,
        user_wants_to_finish=user_wants_to_finish,
        completion_reason=reason,
        requires_human_review=requires_human_review,
        review_reason=review_reason,
        emergency_guidance=emergency_guidance,
        model_name="test-intake-double",
        prompt_version="intake-v4",
    )


class QueueIntakeProvider(IntakeProvider):
    model_name = "test-intake-double"

    def __init__(self, *responses: ComplaintIntakeChatResponse):
        self.responses = deque(responses)
        self.follow_up_counts: list[int] = []

    def analyze(
        self,
        messages: list[ChatMessage],
        current_data: ComplaintExtractedData,
        *,
        follow_up_count: int = 0,
    ) -> ComplaintIntakeChatResponse:
        self.follow_up_counts.append(follow_up_count)
        if not self.responses:
            raise AssertionError("No se configuró una respuesta para el doble de intake.")
        return self.responses.popleft()


class CompleteIntakeProvider(IntakeProvider):
    model_name = "test-intake-double"

    def analyze(
        self,
        messages: list[ChatMessage],
        current_data: ComplaintExtractedData,
        *,
        follow_up_count: int = 0,
    ) -> ComplaintIntakeChatResponse:
        report = " ".join(message.content for message in messages if message.role == "user")
        data = extracted_data(
            descripcion_detallada=report,
            relacion_incidente="testigo",
            categoria_preliminar="ruido",
            distrito="Llorente",
            direccion_exacta="100 metros norte de la escuela",
            tipo_lugar="parque",
            fecha_hora_aproximada="ayer",
        )
        return intake_response(data)


class LocalEmbeddingDouble:
    model_name = "test-hash-embedding"

    def __init__(self, dimensions: int = 1536):
        self.dimensions = dimensions

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for token in text.casefold().split():
            digest = hashlib.sha256(token.encode()).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            vector[index] += 1.0
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(text) for text in texts]


class LocalIncidentAssessmentDouble(IncidentAssessmentProvider):
    model_name = "test-incident-assessment"

    def assess(
        self,
        data: ComplaintExtractedData,
        *,
        incident_summary: str | None,
        initial_quality_reason: str | None,
        contact_available: bool,
    ) -> IncidentAssessment:
        highlighted = data.urgency == "alta"
        review_required = bool(initial_quality_reason)
        return IncidentAssessment(
            possible_emergency=data.urgency == "inmediata",
            emergency_reason=(
                "El escenario de prueba indica urgencia inmediata."
                if data.urgency == "inmediata"
                else None
            ),
            highlight=HighlightAssessment(
                required=highlighted,
                attention_level="prompt" if highlighted else None,
                reasons=["Incidente de mayor cuidado."] if highlighted else [],
                operational_summary=(
                    incident_summary or "Resumen operativo de prueba." if highlighted else None
                ),
                recommended_precautions=["Revisar el incidente."] if highlighted else [],
                evidence=[str(data.urgency)] if highlighted else [],
            ),
            quality_review=QualityReviewAssessment(
                required=review_required,
                review_type="data_quality" if review_required else None,
                issues=[initial_quality_reason] if initial_quality_reason else [],
                admin_summary=(
                    f"Revisión de calidad requerida: {initial_quality_reason}"
                    if initial_quality_reason
                    else None
                ),
                recommended_actions=(
                    [
                        RecommendedAction(
                            code=(
                                "contact_citizen"
                                if contact_available
                                else "dismiss_if_unrecoverable"
                            ),
                            rationale="Acción administrativa de prueba.",
                        )
                    ]
                    if review_required
                    else []
                ),
            ),
        )
