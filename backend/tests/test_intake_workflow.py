from sqlalchemy import select

from app.ai.intake import DeterministicIntakeProvider
from app.models import ComplaintSubmission, HumanReview
from app.schemas import ChatMessage, ComplaintExtractedData, IntakeSubmissionRequest
from app.services.intake import IntakeService

COMPLETE_REPORT = (
    "Ayer vi una fiesta con mucho ruido en un parque del distrito Llorente. "
    "Ubicación: 100 metros norte de la escuela de Llorente."
)

REPORTED_ACCENTED_REPORT = (
    "Fui testigo de un asalto en la parada de bus en la calle principal de "
    "San Joaquín frente a la Tienda Gollo. Esto ocurrió el día lunes 7 de enero "
    "a las 4 pm de la tarde."
)


def test_persistent_intake_collects_and_submits_an_incident(db_session):
    service = IntakeService(db_session, provider=DeterministicIntakeProvider())
    session = service.start()

    response = service.add_user_message(session.id, COMPLETE_REPORT)

    assert response.is_complete is True
    assert response.extracted_data.categoria_preliminar == "ruido"
    assert response.extracted_data.distrito == "Llorente"
    assert response.extracted_data.relacion_incidente == "testigo"
    assert response.summary_text

    incident = service.submit(
        session.id,
        IntakeSubmissionRequest(
            name="Ana Prueba",
            identification="1-2345-6789",
            email="ana@example.com",
            phone="8888-9999",
            truth_confirmation=True,
            data_usage_consent=True,
        ),
    )

    saved = db_session.scalar(
        select(ComplaintSubmission).where(ComplaintSubmission.id == incident.id)
    )
    assert saved.analysis_metadata["source"] == "persistent_intake"
    assert saved.prompt_version == "intake-v2"
    assert saved.name == "Ana Prueba"
    assert saved.identification == "1-2345-6789"
    assert saved.email == "ana@example.com"
    assert saved.phone == "8888-9999"


def test_emergency_signal_creates_human_review(db_session):
    service = IntakeService(db_session, provider=DeterministicIntakeProvider())
    session = service.start()
    report = COMPLETE_REPORT + " Hay una persona inconsciente y está ocurriendo ahora."

    response = service.add_user_message(session.id, report)
    assert response.requires_human_review is True

    incident = service.submit(
        session.id,
        IntakeSubmissionRequest(
            truth_confirmation=True,
            data_usage_consent=True,
        ),
    )
    review = db_session.scalar(select(HumanReview).where(HumanReview.incident_id == incident.id))
    assert review is not None
    assert review.status == "pending"


def test_deterministic_intake_understands_accented_natural_report():
    provider = DeterministicIntakeProvider()

    response = provider.analyze(
        messages=[ChatMessage(role="user", content=REPORTED_ACCENTED_REPORT)],
        current_data=ComplaintExtractedData(),
    )

    assert response.is_complete is True
    assert response.extracted_data.relacion_incidente == "testigo"
    assert response.extracted_data.categoria_preliminar == "robo"
    assert response.extracted_data.distrito == "San Joaquin"
    assert response.extracted_data.tipo_lugar == "otro"
    assert "lunes 7 de enero" in response.extracted_data.fecha_hora_aproximada
    assert "parada de bus" in response.extracted_data.direccion_exacta


def test_deterministic_intake_applies_follow_up_answers_without_repeating_questions():
    provider = DeterministicIntakeProvider()
    first = provider.analyze(
        messages=[
            ChatMessage(
                role="user",
                content=(
                    "Ocurrió un asalto en una parada de bus. "
                    "Ubicación: frente a la Tienda Gollo. Fue ayer a las 4 pm."
                ),
            )
        ],
        current_data=ComplaintExtractedData(),
    )
    assert first.missing_fields == ["relacion_incidente", "distrito"]

    second = provider.analyze(
        messages=[
            ChatMessage(
                role="user",
                content=(
                    "Ocurrió un asalto en una parada de bus. "
                    "Ubicación: frente a la Tienda Gollo. Fue ayer a las 4 pm."
                ),
            ),
            ChatMessage(role="assistant", content=first.assistant_message),
            ChatMessage(
                role="user",
                content="Mi relación es que fui testigo y fue en el distrito de San Joaquín.",
            ),
        ],
        current_data=first.extracted_data,
    )

    assert second.is_complete is True
    assert second.missing_fields == []
    assert second.extracted_data.relacion_incidente == "testigo"
    assert second.extracted_data.distrito == "San Joaquin"
