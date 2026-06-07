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

Debes deducir relacion_incidente a partir de la forma en que escribe el usuario
cuando sea razonable. Por ejemplo: "me asaltaron", "me amenazaron", "fui
agredido" o "me robaron" indican victima; "vi", "observé", "presencié" o
"escuché" indican testigo; "en mi barrio", "cerca de mi casa", "soy vecino" o
"vivo cerca" indican vecino; "en mi negocio", "mi local", "soy comerciante" o
"frente a mi comercio" indican comerciante. Si hay señales contradictorias o
insuficientes, pregunta para confirmar. Si haces una deducción, indica al
usuario que puede corregirte si detecta información incorrecta.

No preguntes si el incidente es recurrente, si continúa ocurriendo o si ha
ocurrido antes. La recurrencia no es un dato requerido y no debe extraerse.

La conversación puede incluir un bloque de estado con información ya extraída.
Debes tratar ese estado como memoria persistente. Conserva todos los campos que
ya tengan valor, salvo que el usuario corrija explícitamente ese dato. Si el
usuario continúa hablando de otros temas, no borres ni conviertas a null los
datos ya capturados. Usa la conversación completa y el estado actual para
devolver siempre la versión acumulada más completa de extracted_data.

Cuando la información esté completa, genera también un resumen final para el
usuario. summary_text debe ser un párrafo en prosa de 3 a 4 oraciones basado en
toda la información recolectada. Redacta summary_text con tono profesional de
reporte policial o reporte administrativo institucional, por ejemplo: "El día
lunes 2 de enero, la víctima reportó que su vehículo fue robado cerca de
Almacenes El Rey, en el distrito de Llorente." No uses lenguaje conversacional,
no escribas en primera persona y no agregues conclusiones no reportadas por el
usuario. No uses el término "persona usuaria" en el resumen; si no hay una
relación más específica como víctima, testigo, vecino o comerciante, utiliza
"persona denunciante". summary_bullets debe incluir puntos específicos y
fáciles de revisar, pero no debe incluir un bullet de descripción detallada. Si
la información aún no está completa, summary_text debe ser null y
summary_bullets debe ser una lista vacía.

Haz una o pocas preguntas por turno. No des asesoría legal, no juzgues, no
confirmes culpabilidad y no inventes datos. Si el usuario describe una emergencia
actual o riesgo inmediato, indica que debe contactar a los servicios de emergencia
o a las autoridades correspondientes.

Devuelve únicamente JSON válido con la forma solicitada.
"""

INTAKE_RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "assistant_message",
        "is_complete",
        "missing_fields",
        "extracted_data",
        "summary_text",
        "summary_bullets",
    ],
    "properties": {
        "assistant_message": {"type": "string"},
        "is_complete": {"type": "boolean"},
        "missing_fields": {"type": "array", "items": {"type": "string"}},
        "summary_text": {"type": ["string", "null"]},
        "summary_bullets": {"type": "array", "items": {"type": "string"}},
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
                        "disturbio_publico",
                        "basura_o_contaminacion",
                        "alumbrado_publico",
                        "obstruccion_via_publica",
                        "animal_peligroso",
                        "consumo_alcohol_drogas",
                        "acoso_o_amenaza",
                        "problema_transito",
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
        summary_text=None,
        summary_bullets=[],
    )


def run_complaint_intake_chat(
    payload: ComplaintIntakeChatRequest,
) -> ComplaintIntakeChatResponse:
    if not payload.messages:
        return _empty_chat_response(
            "Para iniciar, describa la denuncia con el mayor detalle posible. "
            "Incluya qué ocurrió, dónde ocurrió, cuándo ocurrió y los involucrados. "
            "Si detecto algún dato incorrecto, puede indicármelo para corregirlo."
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
        if not validated.is_complete:
            validated.summary_text = None
            validated.summary_bullets = []
        else:
            validated.summary_text = validated.summary_text or _build_summary_text(
                validated.extracted_data
            )
            validated.summary_bullets = validated.summary_bullets or _build_summary_bullets(
                validated.extracted_data
            )
        return validated
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="La respuesta del asistente IA no tuvo el formato esperado.",
        ) from exc


def _build_summary_text(extracted_data: ComplaintExtractedData) -> str:
    data = extracted_data.model_dump()
    fecha = data.get("fecha_hora_aproximada") or "fecha y hora no especificadas"
    relacion_labels = {
        "victima": "víctima",
        "testigo": "testigo",
        "vecino": "vecino",
        "comerciante": "comerciante",
        "otro": "persona denunciante",
    }
    relacion = relacion_labels.get(
        data.get("relacion_incidente"),
        "persona denunciante",
    )
    categoria = data.get("categoria_preliminar") or "incidente reportado"
    distrito = data.get("distrito") or "distrito no especificado"
    direccion = data.get("direccion_exacta") or "ubicación no especificada"
    tipo_lugar = data.get("tipo_lugar") or "lugar no especificado"
    descripcion = data.get("descripcion_detallada") or "No se registraron detalles adicionales."

    return (
        f"El día {fecha}, la {relacion} reportó un caso clasificado preliminarmente como "
        f"{categoria} en la ubicación {direccion}, distrito de {distrito}. "
        f"El incidente fue ubicado en un sitio identificado como {tipo_lugar}. "
        f"Según la información aportada, {descripcion}"
    )


def _build_summary_bullets(extracted_data: ComplaintExtractedData) -> list[str]:
    data = extracted_data.model_dump()
    labels = {
        "relacion_incidente": "Relación con el incidente",
        "categoria_preliminar": "Categoría preliminar",
        "distrito": "Distrito",
        "direccion_exacta": "Dirección exacta",
        "tipo_lugar": "Tipo de lugar",
        "fecha_hora_aproximada": "Fecha y hora aproximada",
    }
    return [
        f"{label}: {data[key]}"
        for key, label in labels.items()
        if data.get(key)
    ]
