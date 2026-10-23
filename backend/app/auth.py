from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuthSession, User

PASSWORD_ALGORITHM = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 600_000
PASSWORD_SALT_BYTES = 16
SESSION_TOKEN_BYTES = 32


def normalize_username(username: str) -> str:
    return username.strip().casefold()


def hash_password(password: str) -> str:
    if len(password) < 12:
        raise ValueError("La contraseña debe tener al menos 12 caracteres.")
    salt = secrets.token_bytes(PASSWORD_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PASSWORD_ITERATIONS,
    )
    encode = base64.urlsafe_b64encode
    return "$".join(
        (
            PASSWORD_ALGORITHM,
            str(PASSWORD_ITERATIONS),
            encode(salt).decode("ascii"),
            encode(digest).decode("ascii"),
        )
    )


def verify_password(password: str, encoded_hash: str) -> bool:
    try:
        algorithm, iterations, encoded_salt, encoded_digest = encoded_hash.split("$", 3)
        if algorithm != PASSWORD_ALGORITHM:
            return False
        salt = base64.urlsafe_b64decode(encoded_salt.encode("ascii"))
        expected_digest = base64.urlsafe_b64decode(encoded_digest.encode("ascii"))
        actual_digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            int(iterations),
        )
    except (TypeError, ValueError, UnicodeError):
        return False
    return hmac.compare_digest(actual_digest, expected_digest)


def digest_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


_DUMMY_PASSWORD_HASH = hash_password(secrets.token_urlsafe(32))


class AuthenticationError(ValueError):
    pass


class AuthService:
    def __init__(self, db: Session, session_ttl_hours: int = 8):
        self.db = db
        self.session_ttl_hours = session_ttl_hours

    def authenticate(self, username: str, password: str) -> tuple[User, str, datetime]:
        user = self.db.scalar(
            select(User).where(User.username == normalize_username(username))
        )
        verified = verify_password(password, user.password_hash if user else _DUMMY_PASSWORD_HASH)
        if user is None or not user.is_active or not verified:
            raise AuthenticationError("Usuario o contraseña inválidos.")

        now = datetime.now(UTC)
        token = secrets.token_urlsafe(SESSION_TOKEN_BYTES)
        expires_at = now + timedelta(hours=self.session_ttl_hours)
        self.db.add(
            AuthSession(
                token_hash=digest_session_token(token),
                user_id=user.id,
                expires_at=expires_at,
            )
        )
        user.last_login_at = now
        self.db.commit()
        self.db.refresh(user)
        return user, token, expires_at

    def user_from_token(self, token: str | None) -> User | None:
        if not token:
            return None
        session = self.db.scalar(
            select(AuthSession).where(AuthSession.token_hash == digest_session_token(token))
        )
        now = datetime.now(UTC)
        expires_at = session.expires_at if session is not None else None
        if expires_at is not None and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if session is None or session.revoked_at is not None or expires_at <= now:
            return None
        user = self.db.get(User, session.user_id)
        if user is None or not user.is_active:
            return None
        session.last_seen_at = now
        self.db.commit()
        return user

    def revoke_token(self, token: str | None) -> None:
        if not token:
            return
        session = self.db.scalar(
            select(AuthSession).where(AuthSession.token_hash == digest_session_token(token))
        )
        if session is not None and session.revoked_at is None:
            session.revoked_at = datetime.now(UTC)
            self.db.commit()

    def create_user(self, username: str, password: str, role: str) -> User:
        normalized_username = normalize_username(username)
        if not normalized_username:
            raise ValueError("El nombre de usuario es obligatorio.")
        if role not in {"police", "administrative"}:
            raise ValueError("El rol debe ser police o administrative.")
        if self.db.scalar(select(User).where(User.username == normalized_username)):
            raise ValueError("El usuario ya existe.")
        user = User(
            username=normalized_username,
            role=role,
            password_hash=hash_password(password),
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user
