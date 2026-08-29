from sqlalchemy import select

from app.models import AuditEvent, ComplaintSubmission, HumanReview
from app.schemas import (
    IntakeFieldObservation,
    IntakeSubmissionRequest,
    InternalIntakeSubmissionRequest,
)
from app.services.intake import IntakeService
from tests.fakes import QueueIntakeProvider, extracted_data, intake_response

COMPLETE_REPORT = (
    "Ayer vi una fiesta con mucho ruido en un parque del distrito Llorente. "
    "Ubicación: 100 metros norte de la escuela de Llorente."
)


def complete_data():
    return extracted_data(
        descripcion_detallada=COMPLETE_REPORT,
        relacion_incidente="testigo",
        categoria_preliminar="ruido",
        distrito="Llorente",
        direccion_exacta="100 metros norte de la escuela de Llorente",
        tipo_lugar="parque",
        fecha_hora_aproximada="ayer",
    )


def submission_request(**overrides):
    values = {
        "truth_confirmation": True,
        "data_usage_consent": True,
    }
    values.update(overrides)
    return IntakeSubmissionRequest(**values)


def test_persistent_intake_collects_and_submits_an_incident(db_session):
    provider = QueueIntakeProvider(intake_response(complete_data()))
    service = IntakeService(db_session, provider=provider)
    session = service.start()

    response = service.add_user_message(session.id, COMPLETE_REPORT)

    assert response.is_complete is True
    assert response.extracted_data.categoria_preliminar == "ruido"
    assert response.extracted_data.distrito == "Llorente"
    assert response.extracted_data.relacion_incidente == "testigo"
    assert response.summary_text

    incident = service.submit(
        session.id,
        submission_request(
            name="Ana Prueba",
            identification="1-2345-6789",
            email="ana@example.com",
            phone="8888-9999",
        ),
    )

    saved = db_session.scalar(
        select(ComplaintSubmission).where(ComplaintSubmission.id == incident.id)
    )
    assert saved.analysis_metadata["source"] == "persistent_intake"
    assert saved.police_input is False
    assert saved.analysis_metadata["completion_reason"] == "all_fields_resolved"
    assert saved.prompt_version == "intake-v4"
    assert saved.name == "Ana Prueba"
    assert saved.identification == "1-2345-6789"
    assert saved.email == "ana@example.com"
    assert saved.phone == "8888-9999"


def test_internal_intake_marks_incident_and_audits_badge(db_session):
    provider = QueueIntakeProvider(intake_response(complete_data()))
    service = IntakeService(db_session, provider=provider)
    session = service.start()
    service.add_user_message(session.id, COMPLETE_REPORT)

    incident = service.submit_internal(
        session.id,
        InternalIntakeSubmissionRequest(
            entered_by_badge="ADM-042",
            truth_confirmation=True,
            data_usage_consent=True,
        ),
    )

    assert incident.police_input is True
    assert incident.entered_by_badge == "ADM-042"
    audit = db_session.scalar(
        select(AuditEvent).where(
            AuditEvent.action == "incident:internal_create",
            AuditEvent.resource_id == str(incident.id),
        )
    )
    assert audit is not None
    assert audit.details == {"police_input": True, "entered_by_badge": "ADM-042"}


def test_emergency_signal_is_recorded_without_creating_quality_review(db_session):
    response = intake_response(
        complete_data(),
        emergency_guidance=True,
    )
    service = IntakeService(db_session, provider=QueueIntakeProvider(response))
    session = service.start()

    analyzed = service.add_user_message(
        session.id,
        COMPLETE_REPORT + " Hay una persona inconsciente y está ocurriendo ahora.",
    )
    assert analyzed.requires_human_review is False
    assert analyzed.emergency_guidance_shown is True

    incident = service.submit(session.id, submission_request())
    review = db_session.scalar(select(HumanReview).where(HumanReview.incident_id == incident.id))
    assert review is None
    assert incident.analysis_metadata["emergency_guidance_shown"] is True


def test_follow_up_state_is_persisted_without_reasking_known_fields(db_session):
    partial = extracted_data(
        descripcion_detallada="Vi un asalto frente a una tienda.",
        categoria_preliminar="robo",
        direccion_exacta="frente a la Tienda Gollo",
        tipo_lugar="otro",
        fecha_hora_aproximada="ayer a las 4 pm",
    )
    first = intake_response(
        partial,
        assistant_message="¿Fue testigo o víctima y en cuál distrito ocurrió?",
        is_complete=False,
    )
    provider = QueueIntakeProvider(first, intake_response(complete_data()))
    service = IntakeService(db_session, provider=provider)
    session = service.start()

    first_result = service.add_user_message(session.id, "Vi un asalto frente a una tienda.")
    second_result = service.add_user_message(
        session.id,
        "Fui testigo y ocurrió en San Joaquín.",
    )

    assert first_result.follow_up_count == 1
    assert second_result.is_complete is True
    assert provider.follow_up_counts == [0, 1]


def test_explicit_finish_allows_partial_report_to_be_saved(db_session):
    partial = extracted_data(
        descripcion_detallada="Un vecino hizo mucho ruido después de las diez de la noche.",
        categoria_preliminar="ruido",
        distrito="Llorente",
        direccion_exacta="150 metros norte del salón comunal de Llorente",
        fecha_hora_aproximada="8 de marzo de 2026 después de las 10 pm",
    )
    partial.field_states.relacion_incidente = IntakeFieldObservation(status="unknown")
    partial.field_states.tipo_lugar = IntakeFieldObservation(status="declined")
    response = intake_response(
        partial,
        assistant_message="Entendido, prepararé el reporte con lo disponible.",
        is_complete=True,
        user_wants_to_finish=True,
        completion_reason="user_finished",
    )
    service = IntakeService(db_session, provider=QueueIntakeProvider(response))
    session = service.start()

    analyzed = service.add_user_message(session.id, "Eso es todo, no sé nada más.")
    incident = service.submit(session.id, submission_request())

    assert analyzed.is_complete is True
    assert analyzed.user_wants_to_finish is True
    assert "relacion_incidente" not in analyzed.missing_fields
    assert "tipo_lugar" not in analyzed.missing_fields
    assert incident.analysis_metadata["completion_reason"] == "user_finished"
    assert set(incident.analysis_metadata["missing_operational_fields"]) == {
        "relacion_incidente",
        "tipo_lugar",
    }
