from __future__ import annotations

import hashlib
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.operational import AGENT_PROMPT_VERSION, OperationalAgent
from app.models import AIInteractionTrace, OperationalSession
from app.schemas import (
    ChatMessage,
    OperationalQueryResponse,
    OperationalSessionResponse,
)

SESSION_CONTEXT_MESSAGES = 24


class OperationalSessionNotFoundError(LookupError):
    pass


def record_operational_interaction(
    db: Session,
    query: str,
    response: OperationalQueryResponse,
    *,
    session_id: str | None = None,
) -> None:
    db.add(
        AIInteractionTrace(
            trace_id=response.trace_id,
            session_id=session_id,
            feature="operational_agent",
            model_name=response.model_name,
            prompt_version=response.prompt_version,
            input_hash=hashlib.sha256(query.encode("utf-8")).hexdigest(),
            latency_ms=response.latency_ms,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            estimated_cost_usd=response.usage.estimated_cost_usd,
            result_metadata={
                "tool_names": [step.tool_name for step in response.steps],
                "tool_successes": sum(step.success for step in response.steps),
                "tool_failures": sum(not step.success for step in response.steps),
                "incident_citations": response.incident_citations,
                "legal_citations": response.legal_citations,
                "requires_human_review": response.requires_human_review,
            },
        )
    )


class OperationalSessionService:
    def __init__(self, db: Session):
        self.db = db

    def start(self, *, model_name: str) -> OperationalSession:
        session = OperationalSession(
            id=str(uuid.uuid4()),
            messages=[],
            model_name=model_name,
            prompt_version=AGENT_PROMPT_VERSION,
        )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return session

    def get(self, session_id: str) -> OperationalSession:
        session = self.db.get(OperationalSession, session_id)
        if session is None:
            raise OperationalSessionNotFoundError(session_id)
        return session

    def to_response(self, session: OperationalSession) -> OperationalSessionResponse:
        return OperationalSessionResponse(
            session_id=session.id,
            messages=[ChatMessage.model_validate(message) for message in session.messages],
            model_name=session.model_name,
            prompt_version=session.prompt_version,
        )

    async def ask(
        self,
        session_id: str,
        query: str,
        agent: OperationalAgent,
    ) -> OperationalQueryResponse:
        session = self.db.scalar(
            select(OperationalSession).where(OperationalSession.id == session_id).with_for_update()
        )
        if session is None:
            raise OperationalSessionNotFoundError(session_id)
        history = [ChatMessage.model_validate(message) for message in session.messages]
        response = await agent.run(query, history=history)
        messages = [*history, ChatMessage(role="user", content=query)]
        messages.append(ChatMessage(role="assistant", content=response.answer))
        session.messages = [
            message.model_dump() for message in messages[-SESSION_CONTEXT_MESSAGES:]
        ]
        session.last_trace_id = response.trace_id
        session.model_name = response.model_name
        session.prompt_version = response.prompt_version
        record_operational_interaction(self.db, query, response, session_id=session.id)
        self.db.commit()
        self.db.refresh(session)
        return response.model_copy(update={"session_id": session.id})
