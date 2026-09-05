from datetime import UTC, datetime, timedelta

import pytest

from app.auth import AuthenticationError, AuthService, hash_password, verify_password


def test_password_hash_is_salted_and_verifiable():
    password = "Una contraseña de prueba segura"
    first_hash = hash_password(password)
    second_hash = hash_password(password)

    assert first_hash != second_hash
    assert verify_password(password, first_hash)
    assert not verify_password("otra contraseña", first_hash)


def test_password_requires_minimum_length():
    with pytest.raises(ValueError, match="12 caracteres"):
        hash_password("corta")


def test_auth_service_issues_and_revokes_opaque_session(db_session):
    service = AuthService(db_session)
    user = service.create_user("POLICE-ADMIN", "Una contraseña segura 123", "police")

    authenticated, token, expires_at = service.authenticate(
        "police-admin",
        "Una contraseña segura 123",
    )

    assert authenticated.id == user.id
    assert authenticated.role == "police"
    assert expires_at > datetime.now(UTC)
    assert service.user_from_token(token).id == user.id

    service.revoke_token(token)

    assert service.user_from_token(token) is None


def test_auth_service_rejects_invalid_credentials(db_session):
    AuthService(db_session).create_user(
        "administrative-admin",
        "Otra contraseña segura 123",
        "administrative",
    )

    with pytest.raises(AuthenticationError):
        AuthService(db_session).authenticate("administrative-admin", "incorrecta")


def test_expired_session_is_not_accepted(db_session):
    service = AuthService(db_session)
    user = service.create_user("expired-user", "Una contraseña segura 456", "police")
    _, token, _ = service.authenticate("expired-user", "Una contraseña segura 456")
    session = user.sessions[0]
    session.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db_session.commit()

    assert service.user_from_token(token) is None
