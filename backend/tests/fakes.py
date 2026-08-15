from __future__ import annotations

import hashlib
import math
from collections import deque

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
) -> ComplaintIntakeChatResponse:
    reason = completion_reason or (
        "all_fields_resolved" if is_complete else "needs_follow_up"
    )
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
        model_name="test-intake-double",
        prompt_version="intake-v3",
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
