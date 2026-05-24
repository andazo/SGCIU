import json
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import HTTPException, status

from .schemas import (
    ComplaintExtractedData,
    ComplaintIntakeChatRequest,
    ComplaintIntakeChatResponse,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

SYSTEM_PROMPT = """
Eres un asistente institucional para recopilar información de denuncias ciudadanas
del cantón de Flores, Costa Rica. Responde siempre en español, con tono claro,
respetuoso y profesional.

Tu objetivo es completar estos datos: descripción detallada del incidente descrito por el usuario, 
relación con el incidente, categoría preliminar, distrito dentro de Flores, dirección exacta,
tipo de lugar y fecha/hora aproximada.

No preguntes si el incidente es recurrente, si continúa ocurriendo o si ha
ocurrido antes. La recurrencia no es un dato requerido y no debe extraerse.

La conversación puede incluir un bloque de estado con información ya extraída.
Debes tratar ese estado como memoria persistente. Conserva todos los campos que
ya tengan valor, salvo que el usuario corrija explícitamente ese dato. Si el
usuario continúa hablando de otros temas, no borres ni conviertas a null los
datos ya capturados. Usa la conversación completa y el estado actual para
devolver siempre la versión acumulada más completa de extracted_data.

Haz una o pocas preguntas por turno. No des asesoría legal, no juzgues, no
confirmes culpabilidad y no inventes datos. Si el usuario describe una emergencia
actual o riesgo inmediato, indica que debe contactar a los servicios de emergencia
o a las autoridades correspondientes.

Devuelve únicamente JSON válido con la forma solicitada.
"""

INTAKE_RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["assistant_message", "is_complete", "missing_fields", "extracted_data"],
    "properties": {
        "assistant_message": {"type": "string"},
        "is_complete": {"type": "boolean"},
        "missing_fields": {"type": "array", "items": {"type": "string"}},
        "extracted_data": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "descripcion_detallada",
                "relacion_incidente",
                "categoria_preliminar",
                "distrito",
                "direccion_exacta",
                "tipo_lugar",
                "fecha_hora_aproximada",
            ],
            "properties": {
                "descripcion_detallada": {"type": ["string", "null"]},
                "relacion_incidente": {
                    "type": ["string", "null"],
                    "enum": ["victima", "testigo", "vecino", "comerciante", "otro", None],
                },
                "categoria_preliminar": {
                    "type": ["string", "null"],
                    "enum": [
                        "ruido",
                        "vehiculo_sospechoso",
                        "venta_drogas",
                        "violencia",
                        "robo",
                        "vandalismo",
                        "persona_sospechosa",
                        "emergencia",
                        "otro",
                        None,
                    ],
                },
                "distrito": {
                    "type": ["string", "null"],
                    "enum": ["San Joaquin", "Barrantes", "Llorente", None],
                },
                "direccion_exacta": {"type": ["string", "null"]},
                "tipo_lugar": {
                    "type": ["string", "null"],
                    "enum": ["establecimiento", "casa", "parque", "escuela", "otro", None],
                },
                "fecha_hora_aproximada": {"type": ["string", "null"]},
            },
        },
    },
}

REQUIRED_EXTRACTED_FIELDS = [
    "descripcion_detallada",
    "relacion_incidente",
    "categoria_preliminar",
    "distrito",
    "direccion_exacta",
    "tipo_lugar",
    "fecha_hora_aproximada",
]


def _empty_chat_response(message: str):
    return ComplaintIntakeChatResponse(
        assistant_message=message,
        is_complete=False,
        missing_fields=REQUIRED_EXTRACTED_FIELDS,
        extracted_data=ComplaintExtractedData(),
    )


def run_complaint_intake_chat(
    payload: ComplaintIntakeChatRequest,
) -> ComplaintIntakeChatResponse:
    if not payload.messages:
        return _empty_chat_response(
            "Para iniciar, describa la denuncia con el mayor detalle posible. "
            "Incluya qué ocurrió, dónde ocurrió, cuándo ocurrió y los involucrados"
        )

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OPENAI_API_KEY no está configurada en el archivo .env.",
        )

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="El paquete openai no está instalado en el backend.",
        ) from exc

    client = OpenAI(api_key=api_key)
    model = os.getenv("OPENAI_MODEL", "gpt-5.4-mini")
    state_message = {
        "role": "system",
        "content": (
            "Estado actual de datos extraídos. Debes conservar estos valores "
            "en la respuesta si el usuario no los corrige explícitamente:\n"
            f"{json.dumps((payload.current_extracted_data or ComplaintExtractedData()).model_dump(), ensure_ascii=False)}"
        ),
    }
    input_messages = [{"role": "system", "content": SYSTEM_PROMPT}, state_message] + [
        message.model_dump() for message in payload.messages
    ]

    try:
        response = client.responses.create(
            model=model,
            input=input_messages,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "complaint_intake_response",
                    "schema": INTAKE_RESPONSE_SCHEMA,
                    "strict": True,
                }
            },
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"No se pudo obtener respuesta del asistente IA: {exc}",
        ) from exc

    try:
        parsed = json.loads(response.output_text)
        validated = ComplaintIntakeChatResponse.model_validate(parsed)
        extracted = validated.extracted_data.model_dump()
        missing_fields = [
            field for field in REQUIRED_EXTRACTED_FIELDS if not extracted.get(field)
        ]
        validated.missing_fields = missing_fields
        validated.is_complete = len(missing_fields) == 0
        return validated
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="La respuesta del asistente IA no tuvo el formato esperado.",
        ) from exc
