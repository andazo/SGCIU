from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.agents.gateway import LocalToolGateway, connect_mcp_gateway
from app.agents.operational import OperationalAgent
from app.api.dependencies import AdminRole
from app.config import get_settings
from app.db import get_db
from app.schemas import OperationalQueryRequest, OperationalQueryResponse

router = APIRouter(prefix="/operational", tags=["operational-agent"])
DbSession = Annotated[Session, Depends(get_db)]


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
