from datetime import datetime

from app.ai.temporal import classify_temporal_context, normalize_temporal_data
from app.schemas import ComplaintExtractedData


REFERENCE = datetime.fromisoformat("2026-07-28T12:00:00-06:00")


def test_named_date_in_future_is_classified_as_future():
    event_datetime, relation, ongoing = classify_temporal_context(
        "El 20 de agosto ocurrió el incidente.", REFERENCE
    )

    assert event_datetime == "2026-08-20T00:00:00-06:00"
    assert relation == "futuro"
    assert ongoing is False


def test_named_date_in_past_is_not_an_active_incident():
    event_datetime, relation, ongoing = classify_temporal_context(
        "El 20 de julio hubo un robo.", REFERENCE
    )

    assert event_datetime == "2026-07-20T00:00:00-06:00"
    assert relation == "pasado"
    assert ongoing is False


def test_current_danger_overrides_historical_event_date():
    _, relation, ongoing = classify_temporal_context(
        "El 20 de julio ocurrió, pero el sujeto sigue en el lugar.", REFERENCE
    )

    assert relation == "en_curso"
    assert ongoing is True


def test_normalization_persists_authoritative_reference():
    data = normalize_temporal_data(
        ComplaintExtractedData(fecha_hora_aproximada="ayer"),
        reference=REFERENCE,
    )

    assert data.reference_datetime == REFERENCE.isoformat()
    assert data.temporal_relation == "pasado"
    assert data.incident_datetime == "2026-07-27T12:00:00-06:00"
