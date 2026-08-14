"""Compatibility adapter for the original stateless intake endpoint."""

from fastapi import HTTPException, status

from app.ai.intake import REQUIRED_FIELDS, get_intake_provider
from app.schemas import (
    ComplaintExtractedData,
    ComplaintIntakeChatRequest,
    ComplaintIntakeChatResponse,
)


def run_complaint_intake_chat(
    payload: ComplaintIntakeChatRequest,
) -> ComplaintIntakeChatResponse:
    if not payload.messages:
        return ComplaintIntakeChatResponse(
            assistant_message=(
                "Para iniciar, describa qué ocurrió, dónde ocurrió y cuándo ocurrió. "
                "Puede corregir cualquier dato interpretado incorrectamente."
            ),
            is_complete=False,
            missing_fields=list(REQUIRED_FIELDS),
            extracted_data=ComplaintExtractedData(),
        )
    try:
        provider = get_intake_provider()
        return provider.analyze(
            payload.messages,
            payload.current_extracted_data or ComplaintExtractedData(),
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="No se pudo completar el análisis de la denuncia.",
        ) from exc
