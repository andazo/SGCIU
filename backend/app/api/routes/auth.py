from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies import AdminRole
from app.auth import AuthenticationError, AuthService
from app.config import get_settings
from app.db import get_db
from app.schemas import AuthLoginRequest, AuthSessionResponse, AuthUserResponse

router = APIRouter(prefix="/auth", tags=["authentication"])
DbSession = Annotated[Session, Depends(get_db)]
AuthorizationHeader = Annotated[str | None, Header(alias="Authorization")]


def _bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.casefold() != "bearer" or not token.strip():
        return None
    return token.strip()


@router.post("/login", response_model=AuthSessionResponse)
def login(payload: AuthLoginRequest, db: DbSession):
    try:
        user, token, expires_at = AuthService(
            db,
            session_ttl_hours=get_settings().auth_session_ttl_hours,
        ).authenticate(payload.username, payload.password)
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    return AuthSessionResponse(
        access_token=token,
        expires_at=expires_at,
        user=AuthUserResponse.model_validate(user),
    )


@router.get("/me", response_model=AuthUserResponse)
def current_user(db: DbSession, actor: AdminRole):
    if actor is None:
        return AuthUserResponse(
            id=0,
            username="development",
            role="administrative",
            is_active=True,
        )
    return AuthUserResponse.model_validate(actor)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(db: DbSession, authorization: AuthorizationHeader):
    AuthService(db).revoke_token(_bearer_token(authorization))
