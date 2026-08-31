from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.agents.operational import AGENT_PROMPT_VERSION, OperationalAgent
from app.models import OperationalSession
from app.schemas import (
    ChatMessage,
    OperationalQueryResponse,
    OperationalSessionResponse,
)

SESSION_CONTEXT_MESSAGES = 24


class OperationalSessionNotFoundError(LookupError):
    pass


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
        session = self.get(session_id)
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
        self.db.commit()
        self.db.refresh(session)
        return response.model_copy(update={"session_id": session.id})

