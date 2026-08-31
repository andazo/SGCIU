from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.agents.gateway import LocalToolGateway, connect_mcp_gateway
from app.agents.operational import OperationalAgent
from app.api.dependencies import AdminRole
from app.config import get_settings
from app.db import get_db
from app.schemas import (
    OperationalQueryRequest,
    OperationalQueryResponse,
    OperationalSessionCreateResponse,
    OperationalSessionResponse,
)
from app.services.operational import (
    OperationalSessionNotFoundError,
    OperationalSessionService,
)

router = APIRouter(prefix="/operational", tags=["operational-agent"])
DbSession = Annotated[Session, Depends(get_db)]


@router.post("/sessions", response_model=OperationalSessionCreateResponse, status_code=201)
async def start_operational_session(db: DbSession, _actor: AdminRole):
    settings = get_settings()
    session = OperationalSessionService(db).start(model_name=settings.openai_model)
    return OperationalSessionCreateResponse(
        session_id=session.id,
        messages=[],
        model_name=session.model_name or settings.openai_model,
        prompt_version=session.prompt_version,
    )


@router.get("/sessions/{session_id}", response_model=OperationalSessionResponse)
async def get_operational_session(session_id: str, db: DbSession, _actor: AdminRole):
    service = OperationalSessionService(db)
    try:
        return service.to_response(service.get(session_id))
    except OperationalSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Sesión operativa no encontrada.") from exc


@router.post(
    "/sessions/{session_id}/messages",
    response_model=OperationalQueryResponse,
)
async def add_operational_message(
    session_id: str,
    payload: OperationalQueryRequest,
    db: DbSession,
    _actor: AdminRole,
):
    service = OperationalSessionService(db)
    try:
        if get_settings().tool_transport == "mcp":
            async with connect_mcp_gateway() as gateway:
                agent = OperationalAgent(gateway)
                return await service.ask(session_id, payload.query, agent)
        return await service.ask(session_id, payload.query, OperationalAgent(LocalToolGateway(db)))
    except OperationalSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Sesión operativa no encontrada.") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/query", response_model=OperationalQueryResponse)
async def query_operational_agent(
    payload: OperationalQueryRequest,
    db: DbSession,
    _actor: AdminRole,
):
    try:
        if get_settings().tool_transport == "mcp":
            async with connect_mcp_gateway() as gateway:
                return await OperationalAgent(gateway).run(payload.query)
        return await OperationalAgent(LocalToolGateway(db)).run(payload.query)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
