from sqlalchemy import select

from app.ai.intake import DeterministicIntakeProvider
from app.models import ComplaintSubmission, HumanReview
from app.schemas import IntakeSubmissionRequest
from app.services.intake import IntakeService

COMPLETE_REPORT = (
    "Ayer vi una fiesta con mucho ruido en un parque del distrito Llorente. "
    "Ubicación: 100 metros norte de la escuela de Llorente."
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
            truth_confirmation=True,
            data_usage_consent=True,
        ),
    )

    saved = db_session.scalar(
        select(ComplaintSubmission).where(ComplaintSubmission.id == incident.id)
    )
    assert saved.analysis_metadata["source"] == "persistent_intake"
    assert saved.prompt_version == "intake-v2"


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
