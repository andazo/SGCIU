from __future__ import annotations

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.schemas import ComplaintExtractedData, TemporalPrecision, TemporalRelation

LOCAL_TIMEZONE = ZoneInfo("America/Costa_Rica")
MONTHS = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}
CURRENT_MARKERS = re.compile(
    r"\b(?:ahora|actualmente|en este momento|sigue|todavia|todavía|"
    r"esta ocurriendo|está ocurriendo)\b",
    re.IGNORECASE,
)
HISTORICAL_MARKERS = re.compile(
    r"\b(?:ayer|anoche|anteayer|el mes pasado|la semana pasada|ocurrio|"
    r"ocurrió|paso|pasó|sucedio|sucedió)\b",
    re.IGNORECASE,
)
RECURRENCE_PATTERN = re.compile(
    r"\b(?:cada\s+(?:día|dia|noche|semana|fin\s+de\s+semana|mes)|"
    r"todos?\s+los?\s+(?:días|dias|noches|fines\s+de\s+semana)|"
    r"recurrente(?:mente)?|frecuentemente|por\s+segund[oa]\s+[^.]{0,40})\b",
    re.IGNORECASE,
)


def current_local_datetime() -> datetime:
    return datetime.now(LOCAL_TIMEZONE)


def _safe_datetime(reference: datetime, year: int, month: int, day: int) -> datetime | None:
    try:
        return reference.replace(
            year=year, month=month, day=day, hour=0, minute=0, second=0, microsecond=0
        )
    except ValueError:
        return None


def _apply_reported_time(value: datetime | None, text: str) -> datetime | None:
    if value is None:
        return None
    match = re.search(r"(?:\b(?:a\s+las|entre\s+las)\s+|T)(\d{1,2}):(\d{2})", text)
    if not match:
        return value
    hour = int(match.group(1))
    minute = int(match.group(2))
    if hour > 23 or minute > 59:
        return value
    return value.replace(hour=hour, minute=minute, second=0, microsecond=0)


def _parse_event_date(value: str, reference: datetime) -> datetime | None:
    normalized = value.casefold()
    if re.search(r"\bmañana\b", normalized):
        return _apply_reported_time(reference + timedelta(days=1), normalized)
    if re.search(r"\bhoy\b", normalized):
        return _apply_reported_time(reference, normalized)
    if re.search(r"\banteayer\b", normalized):
        return _apply_reported_time(reference - timedelta(days=2), normalized)
    if re.search(r"\bayer\b|\banoche\b", normalized):
        return _apply_reported_time(reference - timedelta(days=1), normalized)
    relative = re.search(r"hace\s+(\d+)\s+d[ií]as?", normalized)
    if relative:
        return _apply_reported_time(reference - timedelta(days=int(relative.group(1))), normalized)
    relative_weeks = re.search(r"hace\s+(\d+)\s+semanas?", normalized)
    if relative_weeks:
        return reference - timedelta(days=int(relative_weeks.group(1)) * 7)
    relative_months = re.search(r"hace\s+(\d+)\s+mes(?:es)?", normalized)
    if relative_months:
        return reference - timedelta(days=int(relative_months.group(1)) * 30)
    if "la semana pasada" in normalized:
        return reference - timedelta(days=7)
    if "la próxima semana" in normalized or "la proxima semana" in normalized:
        return reference + timedelta(days=7)
    if "el mes pasado" in normalized:
        return reference - timedelta(days=30)
    if "el próximo mes" in normalized or "el proximo mes" in normalized:
        return reference + timedelta(days=30)
    if "última semana" in normalized or "ultima semana" in normalized:
        # A week-long report has no precise timestamp. Keep the original phrase and
        # use a stable midpoint solely as the temporal anchor for analysis.
        return reference - timedelta(days=3, hours=12)

    iso_match = re.search(r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b", normalized)
    if iso_match:
        return _apply_reported_time(
            _safe_datetime(
                reference, int(iso_match.group(1)), int(iso_match.group(2)), int(iso_match.group(3))
            ),
            normalized,
        )

    numeric_match = re.search(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](20\d{2}))?\b", normalized)
    if numeric_match:
        return _apply_reported_time(
            _safe_datetime(
                reference,
                int(numeric_match.group(3) or reference.year),
                int(numeric_match.group(2)),
                int(numeric_match.group(1)),
            ),
            normalized,
        )

    month_pattern = "|".join(MONTHS)
    named_match = re.search(
        rf"\b(?:el\s+)?(\d{{1,2}})\s+de\s+({month_pattern})(?:\s+de(?:l)?\s+(20\d{{2}}))?\b",
        normalized,
    )
    if named_match:
        return _apply_reported_time(
            _safe_datetime(
                reference,
                int(named_match.group(3) or reference.year),
                MONTHS[named_match.group(2)],
                int(named_match.group(1)),
            ),
            normalized,
        )
    approximate_named = re.search(
        rf"\b(?:a\s+)?(?:principios|inicios|mediados|finales)\s+de\s+({month_pattern})"
        rf"(?:\s+de(?:l)?\s+(20\d{{2}}))?\b",
        normalized,
    )
    if approximate_named:
        marker = approximate_named.group(0)
        day = 5 if "princip" in marker or "inicio" in marker else 15 if "medi" in marker else 25
        return _safe_datetime(
            reference,
            int(approximate_named.group(2) or reference.year),
            MONTHS[approximate_named.group(1)],
            day,
        )
    return None


def temporal_precision(text: str | None) -> TemporalPrecision:
    value = (text or "").casefold()
    if not value:
        return "unknown"
    if re.search(
        r"\b(?:hoy|mañana|ayer|anoche|anteayer|hace\s+\d+|"
        r"(?:última|ultima|próxima|proxima)\s+semana|"
        r"(?:mes|semana)\s+pasad[oa]|(?:próximo|proximo)\s+mes)\b",
        value,
    ):
        return "relative"
    if re.search(r"\b(?:principios|inicios|mediados|finales)\s+de\b", value):
        return "approximate"
    if re.search(r"\b(?:20\d{2}-\d{1,2}-\d{1,2}|\d{1,2}[/-]\d{1,2}|\d{1,2}\s+de\s+)", value):
        return "exact" if re.search(r"\b\d{1,2}:\d{2}\b|\b\d{1,2}\s*(?:am|pm)\b", value) else "day"
    return "unknown"


def classify_temporal_context(
    text: str | None,
    reference: datetime,
) -> tuple[str | None, TemporalRelation, bool]:
    value = (text or "").strip()
    event_datetime = _parse_event_date(value, reference)
    explicit_current = bool(CURRENT_MARKERS.search(value))
    explicit_historical = bool(HISTORICAL_MARKERS.search(value))
    if explicit_current and (event_datetime is None or event_datetime.date() <= reference.date()):
        return event_datetime.isoformat() if event_datetime else None, "en_curso", True
    if event_datetime is not None:
        relation: TemporalRelation = (
            "pasado"
            if event_datetime.date() < reference.date()
            else "futuro"
            if event_datetime.date() > reference.date()
            else "desconocido"
        )
        return event_datetime.isoformat(), relation, False
    if explicit_historical:
        return None, "pasado", False
    return None, "desconocido", False


def normalize_temporal_data(
    data: ComplaintExtractedData,
    *,
    reference: datetime | None = None,
    source_text: str | None = None,
) -> ComplaintExtractedData:
    reference = reference or current_local_datetime()
    temporal_text = " ".join(value for value in (data.fecha_hora_aproximada, source_text) if value)
    event_datetime, relation, ongoing = classify_temporal_context(temporal_text, reference)
    normalized = data.model_copy(deep=True)
    normalized.reference_datetime = reference.isoformat()
    normalized.incident_datetime = event_datetime
    normalized.incident_datetime_precision = temporal_precision(temporal_text)
    normalized.incident_datetime_source = "explicit" if event_datetime else "unknown"
    normalized.temporal_relation = relation
    normalized.is_currently_occurring = ongoing
    recurrence = RECURRENCE_PATTERN.search(temporal_text)
    normalized.is_recurring = recurrence is not None
    normalized.recurrence_pattern = recurrence.group(0).strip() if recurrence else None
    return normalized
