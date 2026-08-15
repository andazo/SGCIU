from dataclasses import replace
from types import SimpleNamespace

from app.ai.intake import SYSTEM_PROMPT, IntakeModelOutput, OpenAIIntakeProvider
from app.config import get_settings
from app.schemas import ChatMessage, ComplaintExtractedData, IntakeFieldObservation
from tests.fakes import extracted_data


class RecordingResponses:
    def __init__(self, output: IntakeModelOutput):
        self.output = output
        self.calls: list[dict[str, object]] = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            output_parsed=self.output,
            usage=SimpleNamespace(input_tokens=120, output_tokens=80),
        )


class RecordingOpenAIClient:
    def __init__(self, output: IntakeModelOutput):
        self.responses = RecordingResponses(output)


def settings():
    return replace(
        get_settings(),
        openai_api_key="test-key-not-used",
        openai_intake_model="gpt-5.6",
        intake_reasoning_effort="high",
        intake_max_follow_ups=4,
    )


def test_openai_intake_uses_reasoning_and_preserves_costa_rican_address():
    candidate = extracted_data(
        descripcion_detallada=(
            "El 8 de marzo de 2026, un vecino de Llorente hizo mucho ruido después "
            "de las 10 de la noche."
        ),
        categoria_preliminar="ruido",
        distrito="Llorente",
        direccion_exacta="150 metros norte del salón comunal de Llorente",
        fecha_hora_aproximada="8 de marzo de 2026 después de las 10 de la noche",
    )
    output = IntakeModelOutput(
        assistant_message=(
            "Para orientar mejor a los oficiales, ¿sabe si el ruido provenía de una casa "
            "u otro tipo de lugar?"
        ),
        user_wants_to_finish=False,
        extracted_data=candidate,
    )
    client = RecordingOpenAIClient(output)
    provider = OpenAIIntakeProvider(settings(), client=client)

    result = provider.analyze(
        [
            ChatMessage(
                role="user",
                content=(
                    "El día 8 de marzo del 2026, un vecino de llorente estaba haciendo "
                    "mucho ruido despúes de las 10 de la noche. La direcicón exacta es "
                    "150 mts norte del salón comunal de llorente."
                ),
            )
        ],
        ComplaintExtractedData(),
    )

    assert result.extracted_data.direccion_exacta == (
        "150 metros norte del salón comunal de Llorente"
    )
    assert result.extracted_data.distrito == "Llorente"
    assert result.extracted_data.relacion_incidente is None
    assert result.extracted_data.field_states.direccion_exacta.evidence
    assert result.is_complete is False
    call = client.responses.calls[0]
    assert call["reasoning"] == {"effort": "high"}
    assert call["store"] is False
    assert call["text_format"] is IntakeModelOutput
    assert "direcciones costarricenses" in call["instructions"]
    assert "150 metros norte" in SYSTEM_PROMPT


def test_explicit_finish_is_enforced_even_if_model_does_not_detect_it():
    current = extracted_data(
        descripcion_detallada="Se reportó ruido fuerte durante la noche.",
        categoria_preliminar="ruido",
        distrito="Llorente",
        direccion_exacta="cerca del salón comunal",
        fecha_hora_aproximada="anoche",
    )
    candidate = current.model_copy(deep=True)
    candidate.field_states.relacion_incidente = IntakeFieldObservation(status="unknown")
    output = IntakeModelOutput(
        assistant_message="¿Desea agregar algún otro detalle?",
        user_wants_to_finish=False,
        extracted_data=candidate,
    )
    provider = OpenAIIntakeProvider(settings(), client=RecordingOpenAIClient(output))

    result = provider.analyze(
        [ChatMessage(role="user", content="Eso es todo, no tengo más información.")],
        current,
    )

    assert result.is_complete is True
    assert result.user_wants_to_finish is True
    assert result.completion_reason == "user_finished"
    assert "prepararé la denuncia" in result.assistant_message.casefold()
    assert result.summary_text


def test_previous_supported_fact_survives_an_incomplete_model_turn():
    current = extracted_data(
        descripcion_detallada="Vi un asalto en una parada de bus.",
        categoria_preliminar="robo",
        direccion_exacta="frente a la Tienda Gollo",
    )
    candidate = extracted_data(
        descripcion_detallada="Vi un asalto en una parada de bus.",
        categoria_preliminar="robo",
    )
    output = IntakeModelOutput(
        assistant_message="¿En cuál distrito ocurrió?",
        user_wants_to_finish=False,
        extracted_data=candidate,
    )
    provider = OpenAIIntakeProvider(settings(), client=RecordingOpenAIClient(output))

    result = provider.analyze(
        [ChatMessage(role="user", content="Fue en San Joaquín.")],
        current,
    )

    assert result.extracted_data.direccion_exacta == "frente a la Tienda Gollo"
    assert result.extracted_data.field_states.direccion_exacta.status == "known"
