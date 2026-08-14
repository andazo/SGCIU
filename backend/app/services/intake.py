from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.ai.intake import REQUIRED_FIELDS, IntakeProvider, get_intake_provider
from app.models import HumanReview, IntakeSession
from app.schemas import (
    ChatMessage,
    ComplaintExtractedData,
    ComplaintSubmissionCreate,
    IntakeSessionResponse,
    IntakeSubmissionRequest,
)
from app.services.incidents import IncidentService

INITIAL_MESSAGE = (
    "Describa la denuncia con el mayor detalle posible, incluyendo qué ocurrió, "
    "dónde y cuándo. Puede corregir cualquier dato que el asistente interprete incorrectamente."
)


class IntakeSessionNotFoundError(LookupError):
    pass


class IncompleteIntakeError(ValueError):
    pass


class IntakeService:
    def __init__(self, db: Session, provider: IntakeProvider | None = None):
        self.db = db
        self.provider = provider or get_intake_provider()

    def start(self) -> IntakeSession:
        session = IntakeSession(
            id=str(uuid.uuid4()),
            messages=[{"role": "assistant", "content": INITIAL_MESSAGE}],
            extracted_data=ComplaintExtractedData().model_dump(),
            prompt_version="intake-v2",
            model_name=self.provider.model_name,
        )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return session

    def get(self, session_id: str) -> IntakeSession:
        session = self.db.get(IntakeSession, session_id)
        if session is None:
            raise IntakeSessionNotFoundError(session_id)
        return session

    def add_user_message(self, session_id: str, content: str) -> IntakeSessionResponse:
        session = self.get(session_id)
        messages = [ChatMessage.model_validate(message) for message in session.messages]
        messages.append(ChatMessage(role="user", content=content))
        stored_data = dict(session.extracted_data)
        previous_workflow = stored_data.pop("_workflow", {})
        current_data = ComplaintExtractedData.model_validate(stored_data)
        result = self.provider.analyze(messages, current_data)
        messages.append(ChatMessage(role="assistant", content=result.assistant_message))

        session.messages = [message.model_dump() for message in messages]
        session.extracted_data = result.extracted_data.model_dump()
        session.summary_text = result.summary_text
        session.is_complete = result.is_complete
        session.model_name = result.model_name
        session.prompt_version = result.prompt_version
        metadata = dict(session.extracted_data)
        metadata["_workflow"] = {
            "requires_human_review": (
                bool(previous_workflow.get("requires_human_review")) or result.requires_human_review
            ),
            "review_reason": result.review_reason or previous_workflow.get("review_reason"),
        }
        session.extracted_data = metadata
        self.db.commit()
        self.db.refresh(session)
        return self.to_response(session)

    def submit(self, session_id: str, payload: IntakeSubmissionRequest):
        session = self.get(session_id)
        response = self.to_response(session)
        if not session.is_complete:
            raise IncompleteIntakeError("La conversación todavía tiene campos pendientes.")
        workflow = session.extracted_data.get("_workflow", {})
        extracted = dict(session.extracted_data)
        extracted.pop("_workflow", None)
        incident_payload = ComplaintSubmissionCreate(
            name=payload.name,
            email=payload.email,
            phone=payload.phone,
            ai_extracted_data=ComplaintExtractedData.model_validate(extracted),
            ai_summary_text=session.summary_text,
            analysis_metadata={
                "source": "persistent_intake",
                "session_id": session.id,
                "confidence_by_field": (
                    response.extracted_data.confidence_by_field.model_dump(exclude_none=True)
                ),
            },
            requires_human_review=bool(workflow.get("requires_human_review")),
            review_reason=workflow.get("review_reason"),
            model_name=session.model_name,
            prompt_version=session.prompt_version,
            truth_confirmation=payload.truth_confirmation,
            data_usage_consent=payload.data_usage_consent,
        )
        incident = IncidentService(self.db).create(incident_payload)
        if incident.requires_human_review:
            self.db.add(
                HumanReview(
                    incident_id=incident.id,
                    reason=incident.review_reason or "Revisión solicitada por el flujo de intake.",
                )
            )
            self.db.commit()
        return incident

    def to_response(self, session: IntakeSession) -> IntakeSessionResponse:
        extracted = dict(session.extracted_data or {})
        workflow = extracted.pop("_workflow", {})
        data = ComplaintExtractedData.model_validate(extracted)
        values = data.model_dump()
        missing = [field for field in REQUIRED_FIELDS if not values.get(field)]
        return IntakeSessionResponse(
            session_id=session.id,
            messages=[ChatMessage.model_validate(message) for message in session.messages],
            is_complete=session.is_complete,
            missing_fields=missing,
            extracted_data=data,
            summary_text=session.summary_text,
            requires_human_review=bool(workflow.get("requires_human_review")),
            review_reason=workflow.get("review_reason"),
            model_name=session.model_name,
            prompt_version=session.prompt_version,
        )
