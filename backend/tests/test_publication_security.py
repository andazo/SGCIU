from __future__ import annotations

import hashlib
import logging
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app import security
from app.api.dependencies import require_admin
from app.auth import AuthService
from app.config import get_settings
from app.logging_config import JsonFormatter
from app.main import app
from app.models import IntakeSession, SecurityRequestBucket


def test_citizen_session_requires_its_separate_capability(db_session):
    with TestClient(app) as client:
        first = client.post("/v1/intake/sessions").json()
        second = client.post("/v1/intake/sessions").json()
        path = f"/v1/intake/sessions/{first['session_id']}"
        assert client.get(path).status_code == 404
        wrong = {"X-Intake-Token": second["access_token"]}
        assert client.get(path, headers=wrong).status_code == 404
        assert (
            client.post(path + "/messages", headers=wrong, json={"content": "private"}).status_code
            == 404
        )
        token = first["access_token"]
        response = client.get(path, headers={"X-Intake-Token": token})
        assert response.status_code == 200
        assert token not in response.text
        session = db_session.get(IntakeSession, first["session_id"])
        assert session.access_token_hash == hashlib.sha256(token.encode()).hexdigest()
        session.created_at = datetime.now(UTC) - timedelta(hours=25)
        db_session.commit()
        assert client.get(path, headers={"X-Intake-Token": token}).status_code == 404


def test_public_and_internal_sessions_cannot_be_interchanged():
    with TestClient(app) as client:
        citizen = client.post("/v1/intake/sessions").json()
        internal = client.post("/v1/internal-intake/sessions").json()
        assert (
            client.get(
                f"/v1/intake/sessions/{internal['session_id']}",
                headers={"X-Intake-Token": citizen["access_token"]},
            ).status_code
            == 404
        )
        assert (
            client.post(
                f"/v1/internal-intake/sessions/{citizen['session_id']}/messages",
                json={"content": "Attempt to change session provenance"},
            ).status_code
            == 404
        )


def test_institutional_conversations_are_owned_by_the_authenticated_user(db_session):
    service = AuthService(db_session)
    alice = service.create_user("alice.security", "Test password Alice 2026", "police")
    bob = service.create_user("bob.security", "Test password Bob 2026", "administrative")
    try:
        with TestClient(app) as client:
            app.dependency_overrides[require_admin] = lambda: alice
            internal = client.post("/v1/internal-intake/sessions").json()
            operational = client.post("/v1/operational/sessions").json()
            path = f"/v1/operational/sessions/{operational['session_id']}"
            assert client.get(path).status_code == 200
            app.dependency_overrides[require_admin] = lambda: bob
            assert client.get(path).status_code == 404
            assert (
                client.post(path + "/messages", json={"query": "Read Alice's chat"}).status_code
                == 404
            )
            assert (
                client.post(
                    f"/v1/internal-intake/sessions/{internal['session_id']}/messages",
                    json={"content": "Read Alice's intake"},
                ).status_code
                == 404
            )
    finally:
        app.dependency_overrides.pop(require_admin, None)


def test_a_completed_intake_cannot_be_submitted_twice():
    with TestClient(app) as client:
        start = client.post("/v1/intake/sessions").json()
        headers = {"X-Intake-Token": start["access_token"]}
        path = f"/v1/intake/sessions/{start['session_id']}"
        assert (
            client.post(
                path + "/messages",
                headers=headers,
                json={"content": "Ruido ayer en un parque de Llorente."},
            ).status_code
            == 200
        )
        consent = {"truth_confirmation": True, "data_usage_consent": True}
        assert client.post(path + "/submit", headers=headers, json=consent).status_code == 201
        assert client.post(path + "/submit", headers=headers, json=consent).status_code == 409
        assert (
            client.post(
                path + "/messages", headers=headers, json={"content": "Change submitted report"}
            ).status_code
            == 409
        )


def test_validation_does_not_echo_password_or_contact_payload():
    with TestClient(app) as client:
        secret = "sensitive-password-that-must-never-be-echoed"
        response = client.post("/v1/auth/login", json={"username": "x", "password": secret})
        assert response.status_code == 422
        assert secret not in response.text
        assert "input" not in response.text
        assert response.headers["Cache-Control"] == "no-store"
        assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_body_limits_cover_declared_and_streamed_requests():
    with TestClient(app) as client:
        assert (
            client.post(
                "/submissions",
                content=b"x",
                headers={
                    "Content-Length": str(security.MAX_BODY_BYTES + 1),
                },
            ).status_code
            == 413
        )

        def chunks():
            yield b"x" * 32_769
            yield b"x" * 32_769

        assert client.post("/submissions", content=chunks()).status_code == 413


def test_exception_logging_excludes_provider_and_sql_error_text():
    secret = "private contact or provider credential"
    try:
        raise ValueError(secret)
    except ValueError:
        record = logging.LogRecord(
            "test", logging.ERROR, "", 0, "Operation failed", (), sys.exc_info()
        )
    result = JsonFormatter().format(record)
    assert secret not in result
    assert "ValueError" in result


@pytest.fixture
def production_security(monkeypatch):
    settings = replace(get_settings(), app_env="production", require_admin_auth=True)
    monkeypatch.setattr(security, "get_settings", lambda: settings)


def test_login_is_throttled_by_account_even_if_forwarded_ip_changes(production_security):
    with TestClient(app) as client:
        for i in range(5):
            response = client.post(
                "/v1/auth/login",
                headers={"X-Forwarded-For": f"203.0.113.{i}"},
                json={"username": "unknown.account", "password": "incorrect-password"},
            )
            assert response.status_code == 401
        response = client.post(
            "/v1/auth/login",
            headers={"X-Forwarded-For": "198.51.100.5"},
            json={"username": "unknown.account", "password": "incorrect-password"},
        )
        assert response.status_code == 429
        assert int(response.headers["Retry-After"]) > 0
        assert client.get("/ready").status_code == 200


@pytest.mark.parametrize("path", ["/complaints", "/submissions", "/ai/intake/chat"])
def test_legacy_direct_write_paths_are_disabled_in_production(production_security, path):
    with TestClient(app) as client:
        assert client.post(path, json={}).status_code == 404


def test_quota_rollover_and_no_raw_identifiers_are_stored(db_session):
    limit = [("user-private@example.test", 2, 60)]
    security.consume_quotas(limit, now=1)
    security.consume_quotas(limit, now=2)
    with pytest.raises(security.QuotaExceeded):
        security.consume_quotas(limit, now=3)
    security.consume_quotas(limit, now=60)
    rows = list(db_session.scalars(select(SecurityRequestBucket)))
    assert len(rows) == 1
    assert len(rows[0].key) == 64 and "private" not in rows[0].key


def test_concurrent_instances_cannot_overrun_a_shared_quota(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'quota.db'}")
    SecurityRequestBucket.__table__.create(engine)
    monkeypatch.setattr(security, "SessionLocal", sessionmaker(bind=engine))

    def attempt(_):
        try:
            security.consume_quotas([("global", 7, 60)], now=10)
            return True
        except security.QuotaExceeded:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(attempt, range(30))) == 7
    engine.dispose()
