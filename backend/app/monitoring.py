from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

HTTP_REQUESTS = Counter(
    "sgciu_http_requests_total",
    "Solicitudes HTTP procesadas por SGCIU.",
    ("method", "route", "status_code"),
)
HTTP_REQUEST_DURATION = Histogram(
    "sgciu_http_request_duration_seconds",
    "Duración de solicitudes HTTP por ruta normalizada.",
    ("method", "route"),
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 90),
)
HTTP_IN_PROGRESS = Gauge(
    "sgciu_http_requests_in_progress",
    "Solicitudes HTTP actualmente en proceso.",
)
AI_CALLS = Counter(
    "sgciu_ai_calls_total",
    "Operaciones de IA completadas, agrupadas por funcionalidad y resultado.",
    ("feature", "model", "status"),
)
AI_DURATION = Histogram(
    "sgciu_ai_call_duration_seconds",
    "Duración de operaciones de IA.",
    ("feature", "model"),
    buckets=(0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300),
)
AI_INPUT_TOKENS = Counter(
    "sgciu_ai_input_tokens_total",
    "Tokens de entrada consumidos por operaciones de IA exitosas.",
    ("feature", "model"),
)
AI_OUTPUT_TOKENS = Counter(
    "sgciu_ai_output_tokens_total",
    "Tokens de salida consumidos por operaciones de IA exitosas.",
    ("feature", "model"),
)
AI_ESTIMATED_COST = Counter(
    "sgciu_ai_estimated_cost_usd_total",
    "Coste acumulado estimado de operaciones de IA en USD.",
    ("feature", "model"),
)
DATABASE_READY = Gauge(
    "sgciu_database_ready",
    "Estado del último chequeo de disponibilidad de base de datos (1=ready, 0=error).",
)


def normalized_route(scope: dict[str, object]) -> str:
    route = scope.get("route")
    path = getattr(route, "path", None)
    return str(path) if path else "unmatched"


def record_http_request(
    *, method: str, route: str, status_code: int, duration_seconds: float
) -> None:
    HTTP_REQUESTS.labels(method=method, route=route, status_code=str(status_code)).inc()
    HTTP_REQUEST_DURATION.labels(method=method, route=route).observe(duration_seconds)


def record_ai_call(
    *,
    feature: str,
    model: str,
    status: str,
    duration_seconds: float,
    input_tokens: int = 0,
    output_tokens: int = 0,
    estimated_cost_usd: float = 0.0,
) -> None:
    if status not in {"success", "error"}:
        raise ValueError("El estado de monitorización de IA debe ser success o error.")
    if min(duration_seconds, input_tokens, output_tokens, estimated_cost_usd) < 0:
        raise ValueError("Las métricas de IA no pueden ser negativas.")
    AI_CALLS.labels(feature=feature, model=model, status=status).inc()
    AI_DURATION.labels(feature=feature, model=model).observe(duration_seconds)
    if status == "success":
        AI_INPUT_TOKENS.labels(feature=feature, model=model).inc(input_tokens)
        AI_OUTPUT_TOKENS.labels(feature=feature, model=model).inc(output_tokens)
        AI_ESTIMATED_COST.labels(feature=feature, model=model).inc(estimated_cost_usd)


def prometheus_payload() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST
