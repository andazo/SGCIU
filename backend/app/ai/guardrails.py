from __future__ import annotations

import re
from dataclasses import dataclass

from app.schemas import ComplaintExtractedData

EMERGENCY_PATTERNS = (
    r"\b(?:arma|disparo|balacera|incendio)\b",
    r"\b(?:me están atacando|está ocurriendo ahora|riesgo inmediato)\b",
    r"\b(?:herido grave|persona inconsciente)\b",
)
PROMPT_INJECTION_PATTERNS = (
    r"ignora (?:todas )?(?:las )?instrucciones",
    r"revela (?:tu )?(?:prompt|mensaje del sistema)",
    r"actúa como (?:administrador|developer|sistema)",
)


@dataclass(frozen=True, slots=True)
class GuardrailResult:
    emergency_guidance: bool = False
    requires_human_review: bool = False
    review_reason: str | None = None


def evaluate_user_message(content: str) -> GuardrailResult:
    normalized = content.casefold()
    if any(re.search(pattern, normalized) for pattern in PROMPT_INJECTION_PATTERNS):
        return GuardrailResult(
            requires_human_review=True,
            review_reason="El mensaje contiene instrucciones dirigidas a manipular el asistente.",
        )
    if any(re.search(pattern, normalized) for pattern in EMERGENCY_PATTERNS):
        return GuardrailResult(
            emergency_guidance=True,
        )
    return GuardrailResult()


def evaluate_analysis(data: ComplaintExtractedData) -> GuardrailResult:
    confidence_scores = data.confidence_by_field.model_dump(exclude_none=True)
    low_confidence = [field for field, score in confidence_scores.items() if score < 0.55]
    if low_confidence:
        return GuardrailResult(
            requires_human_review=True,
            review_reason=(
                "La extracción presenta baja confianza en: " + ", ".join(low_confidence)
            ),
        )
    if data.urgency == "inmediata":
        return GuardrailResult(
            emergency_guidance=True,
        )
    return GuardrailResult()
