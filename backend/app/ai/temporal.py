from __future__ import annotations

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.schemas import ComplaintExtractedData, TemporalRelation

LOCAL_TIMEZONE = ZoneInfo("America/Costa_Rica")
MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
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


def current_local_datetime() -> datetime:
    return datetime.now(LOCAL_TIMEZONE)


def _safe_datetime(reference: datetime, year: int, month: int, day: int) -> datetime | None:
    try:
        return reference.replace(
            year=year, month=month, day=day, hour=0, minute=0, second=0, microsecond=0
        )
    except ValueError:
        return None


def _parse_event_date(value: str, reference: datetime) -> datetime | None:
    normalized = value.casefold()
    if re.search(r"\bhoy\b", normalized):
        return reference
    if re.search(r"\banteayer\b", normalized):
        return reference - timedelta(days=2)
    if re.search(r"\bayer\b|\banoche\b", normalized):
        return reference - timedelta(days=1)
    relative = re.search(r"hace\s+(\d+)\s+d[ií]as?", normalized)
    if relative:
        return reference - timedelta(days=int(relative.group(1)))

    iso_match = re.search(r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b", normalized)
    if iso_match:
        return _safe_datetime(
            reference, int(iso_match.group(1)), int(iso_match.group(2)), int(iso_match.group(3))
        )

    numeric_match = re.search(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](20\d{2}))?\b", normalized)
    if numeric_match:
        return _safe_datetime(
            reference,
            int(numeric_match.group(3) or reference.year),
            int(numeric_match.group(2)),
            int(numeric_match.group(1)),
        )

    month_pattern = "|".join(MONTHS)
    named_match = re.search(
        rf"\b(?:el\s+)?(\d{{1,2}})\s+de\s+({month_pattern})(?:\s+de(?:l)?\s+(20\d{{2}}))?\b",
        normalized,
    )
    if named_match:
        return _safe_datetime(
            reference,
            int(named_match.group(3) or reference.year),
            MONTHS[named_match.group(2)],
            int(named_match.group(1)),
        )
    return None


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
            "pasado" if event_datetime.date() < reference.date()
            else "futuro" if event_datetime.date() > reference.date()
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
    temporal_text = " ".join(
        value for value in (data.fecha_hora_aproximada, source_text) if value
    )
    event_datetime, relation, ongoing = classify_temporal_context(temporal_text, reference)
    normalized = data.model_copy(deep=True)
    normalized.reference_datetime = reference.isoformat()
    normalized.incident_datetime = event_datetime
    normalized.temporal_relation = relation
    normalized.is_currently_occurring = ongoing
    return normalized
