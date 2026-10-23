from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.auth import AuthService
from app.config import Settings, get_settings
from app.db import get_db
from app.models import User

AdminKeyHeader = Annotated[str | None, Header(alias="X-Admin-Key")]
AuthorizationHeader = Annotated[str | None, Header(alias="Authorization")]
DbSession = Annotated[Session, Depends(get_db)]


def validate_admin_key(provided_key: str | None, settings: Settings) -> bool:
    if not settings.require_admin_auth:
        return True
    if not settings.admin_api_key or not provided_key:
        return False
    return secrets.compare_digest(provided_key, settings.admin_api_key)


def _bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.casefold() != "bearer" or not token.strip():
        return None
    return token.strip()


def require_admin(
    x_admin_key: AdminKeyHeader = None,
    authorization: AuthorizationHeader = None,
    db: DbSession = None,
) -> User | None:
    settings = get_settings()
    if not settings.require_admin_auth:
        return None

    user = AuthService(db, session_ttl_hours=settings.auth_session_ttl_hours).user_from_token(
        _bearer_token(authorization)
    )
    if user is not None:
        return user

    # Transitional compatibility for existing integrations. New clients must use Bearer auth.
    if not settings.is_production and validate_admin_key(x_admin_key, settings):
        return None
    raise HTTPException(
        status_code=401,
        detail="Credenciales inválidas o sesión expirada.",
        headers={"WWW-Authenticate": "Bearer"},
    )


AdminRole = Annotated[User | None, Depends(require_admin)]
