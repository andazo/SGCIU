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


def test_named_date_preserves_reported_clock_time_and_precision():
    data = normalize_temporal_data(
        ComplaintExtractedData(fecha_hora_aproximada="viernes 14 de agosto de 2026 a las 22:40"),
        reference=REFERENCE,
    )

    assert data.incident_datetime == "2026-08-14T22:40:00-06:00"
    assert data.incident_datetime_precision == "exact"
    assert data.incident_datetime_source == "explicit"


def test_relative_weeks_and_approximate_months_are_normalized():
    weeks = normalize_temporal_data(
        ComplaintExtractedData(fecha_hora_aproximada="hace 3 semanas"),
        reference=REFERENCE,
    )
    approximate = normalize_temporal_data(
        ComplaintExtractedData(fecha_hora_aproximada="a finales de junio de 2026"),
        reference=REFERENCE,
    )

    assert weeks.incident_datetime == "2026-07-07T12:00:00-06:00"
    assert weeks.incident_datetime_precision == "relative"
    assert approximate.incident_datetime == "2026-06-25T00:00:00-06:00"
    assert approximate.incident_datetime_precision == "approximate"


def test_recurrence_is_preserved_as_structured_temporal_context():
    data = normalize_temporal_data(
        ComplaintExtractedData(
            fecha_hora_aproximada="todos los fines de semana durante la noche"
        ),
        reference=REFERENCE,
    )

    assert data.is_recurring is True
    assert data.recurrence_pattern == "todos los fines de semana"


def test_relative_interval_and_future_expression_are_normalized():
    interval = normalize_temporal_data(
        ComplaintExtractedData(
            fecha_hora_aproximada="entre las 05:30 y 07:00 durante la última semana"
        ),
        reference=REFERENCE,
    )
    future = normalize_temporal_data(
        ComplaintExtractedData(fecha_hora_aproximada="mañana a las 19:30"),
        reference=REFERENCE,
    )

    assert interval.incident_datetime == "2026-07-25T00:00:00-06:00"
    assert interval.incident_datetime_precision == "relative"
    assert interval.temporal_relation == "pasado"
    assert future.incident_datetime == "2026-07-29T19:30:00-06:00"
    assert future.temporal_relation == "futuro"
