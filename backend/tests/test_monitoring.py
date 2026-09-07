from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db import get_db
from app.main import app
from app.monitoring import prometheus_payload, record_ai_call

client = TestClient(app)


def test_metrics_endpoint_exposes_bounded_http_route_labels():
    response = client.get("/v1/incidents/999999")
    assert response.status_code == 404

    metrics = client.get("/metrics")

    assert metrics.status_code == 200
    assert metrics.headers["content-type"].startswith("text/plain")
    assert 'route="/incidents/{incident_id:int}"' in metrics.text
    assert 'route="/v1/incidents/999999"' not in metrics.text
    assert "sgciu_http_request_duration_seconds_bucket" in metrics.text


def test_ai_metrics_capture_tokens_cost_and_failures_without_payloads():
    record_ai_call(
        feature="monitoring_test",
        model="deterministic-model",
        status="success",
        duration_seconds=0.25,
        input_tokens=120,
        output_tokens=30,
        estimated_cost_usd=0.0123,
    )
    record_ai_call(
        feature="monitoring_test",
        model="deterministic-model",
        status="error",
        duration_seconds=0.1,
    )

    payload, _ = prometheus_payload()
    metrics = payload.decode()

    assert (
        'sgciu_ai_calls_total{feature="monitoring_test",model="deterministic-model",'
        'status="success"} 1.0'
    ) in metrics
    assert (
        'sgciu_ai_calls_total{feature="monitoring_test",model="deterministic-model",'
        'status="error"} 1.0'
    ) in metrics
    assert (
        'sgciu_ai_input_tokens_total{feature="monitoring_test",'
        'model="deterministic-model"} 120.0'
    ) in metrics
    assert "0.0123" in metrics


def test_ai_metrics_reject_negative_values():
    with pytest.raises(ValueError, match="negativas"):
        record_ai_call(
            feature="monitoring_test",
            model="deterministic-model",
            status="success",
            duration_seconds=-1,
        )


def test_readiness_returns_503_and_updates_metric_when_database_fails():
    class BrokenSession:
        def execute(self, _statement):
            raise RuntimeError("database unavailable")

    def broken_database():
        yield BrokenSession()

    app.dependency_overrides[get_db] = broken_database
    try:
        response = client.get("/ready")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 503
    payload, _ = prometheus_payload()
    assert "sgciu_database_ready 0.0" in payload.decode()
