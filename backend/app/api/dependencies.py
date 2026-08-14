from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import Depends, Header, HTTPException

from app.config import Settings, get_settings

AdminKeyHeader = Annotated[str | None, Header(alias="X-Admin-Key")]


def validate_admin_key(provided_key: str | None, settings: Settings) -> bool:
    if not settings.require_admin_auth:
        return True
    if not settings.admin_api_key or not provided_key:
        return False
    return secrets.compare_digest(provided_key, settings.admin_api_key)


def require_admin(x_admin_key: AdminKeyHeader = None) -> str:
    settings = get_settings()
    if settings.require_admin_auth and not settings.admin_api_key:
        raise HTTPException(
            status_code=503,
            detail="La autenticación administrativa no está configurada.",
        )
    if not validate_admin_key(x_admin_key, settings):
        raise HTTPException(status_code=401, detail="Credenciales administrativas inválidas.")
    return "admin"


AdminRole = Annotated[str, Depends(require_admin)]
