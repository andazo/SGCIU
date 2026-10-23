from __future__ import annotations

import hashlib
import time
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.intake import (
    PROMPT_VERSION,
    IntakeProvider,
    actionable_missing_fields,
    get_intake_provider,
    reconcile_field_states,
    unresolved_fields,
)
from app.models import AIInteractionTrace, AuditEvent, IntakeSession
from app.schemas import (
    ChatMessage,
    ComplaintExtractedData,
    ComplaintSubmissionCreate,
    IntakeSessionResponse,
    IntakeSubmissionRequest,
    InternalIntakeSubmissionRequest,
    RegistrationMode,
)
from app.services.incidents import IncidentService

EMERGENCY_NOTICE = (
    "SGCIU no es un servicio de atención de emergencias ni garantiza respuesta inmediata. "
    "Si el incidente está ocurriendo ahora, existe peligro o hay personas heridas, "
    "comuníquese inmediatamente con el 9-1-1. Puede continuar registrando la información "
    "como antecedente municipal, pero este registro no sustituye una llamada de emergencia."
)
INITIAL_MESSAGE = (
    "Describa la denuncia con el mayor detalle posible, incluyendo qué ocurrió, "
    "dónde y cuándo. Puede corregir cualquier dato que el asistente interprete incorrectamente "
    "y, si no conoce más detalles, puede indicarlo en cualquier momento."
)


class IntakeSessionNotFoundError(LookupError):
    pass


class IncompleteIntakeError(ValueError):
    pass


class IntakeService:
    def __init__(
        self,
        db: Session,
        provider: IntakeProvider | None = None,
        *,
        process_semantic: bool = True,
    ):
        self.db = db
        self.provider = provider or get_intake_provider()
        self.process_semantic = process_semantic

    def start(
        self,
        registration_mode: RegistrationMode = "complete",
        *,
        access_token: str | None = None,
        audience: str = "citizen",
        owner_user_id: int | None = None,
    ) -> IntakeSession:
        session = IntakeSession(
            id=str(uuid.uuid4()),
            access_token_hash=(
                hashlib.sha256(access_token.encode()).hexdigest() if access_token else None
            ),
            audience=audience,
            owner_user_id=owner_user_id,
            registration_mode=registration_mode,
            messages=[{"role": "assistant", "content": INITIAL_MESSAGE}],
            extracted_data=ComplaintExtractedData().model_dump(),
            prompt_version=PROMPT_VERSION,
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
        session = self.db.scalar(
            select(IntakeSession)
            .where(IntakeSession.id == session_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if session is None:
            raise IntakeSessionNotFoundError(session_id)
        if session.submitted_at is not None:
            raise IncompleteIntakeError("La sesión ya fue enviada; inicie un nuevo reporte.")
        if len(session.messages) >= 41:
            raise IncompleteIntakeError("Se alcanzó el límite de mensajes de esta sesión.")
        messages = [ChatMessage.model_validate(message) for message in session.messages]
        if sum(len(message.content) for message in messages) + len(content) > 64_000:
            raise IncompleteIntakeError("Se alcanzó el límite de texto de esta sesión.")
        messages.append(ChatMessage(role="user", content=content))
        stored_data = dict(session.extracted_data)
        previous_workflow = stored_data.pop("_workflow", {})
        current_data = reconcile_field_states(ComplaintExtractedData.model_validate(stored_data))
        previous_follow_ups = int(previous_workflow.get("follow_up_count", 0))
        trace_id = str(uuid.uuid4())
        started = time.perf_counter()
        try:
            result = self.provider.analyze(
                messages,
                current_data,
                follow_up_count=previous_follow_ups,
                emergency_guidance_already_shown=bool(
                    previous_workflow.get("emergency_guidance_shown")
                ),
            )
        except Exception as exc:
            self.db.add(
                AIInteractionTrace(
                    trace_id=trace_id,
                    session_id=session.id,
                    feature="citizen_intake",
                    model_name=self.provider.model_name,
                    prompt_version=session.prompt_version,
                    input_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                    latency_ms=round((time.perf_counter() - started) * 1000, 2),
                    success=False,
                    result_metadata={"error_type": type(exc).__name__},
                )
            )
            self.db.commit()
            raise
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        messages.append(ChatMessage(role="assistant", content=result.assistant_message))

        session.messages = [message.model_dump() for message in messages]
        session.extracted_data = result.extracted_data.model_dump()
        session.summary_text = result.summary_text
        session.is_complete = result.is_complete
        session.model_name = result.model_name
        session.prompt_version = result.prompt_version
        session.last_trace_id = trace_id
        follow_up_count = previous_follow_ups + (0 if result.is_complete else 1)
        metadata = dict(session.extracted_data)
        metadata["_workflow"] = {
            "requires_human_review": (
                bool(previous_workflow.get("requires_human_review")) or result.requires_human_review
            ),
            "review_reason": result.review_reason or previous_workflow.get("review_reason"),
            "emergency_guidance_shown": (
                bool(previous_workflow.get("emergency_guidance_shown")) or result.emergency_guidance
            ),
            "follow_up_count": follow_up_count,
            "user_wants_to_finish": result.user_wants_to_finish,
            "completion_reason": result.completion_reason,
            "missing_fields": result.missing_fields,
            "unresolved_fields": unresolved_fields(result.extracted_data),
        }
        session.extracted_data = metadata
        usage = self.provider.last_usage
        self.db.add(
            AIInteractionTrace(
                trace_id=trace_id,
                session_id=session.id,
                feature="citizen_intake",
                model_name=result.model_name or self.provider.model_name,
                prompt_version=result.prompt_version,
                input_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                latency_ms=latency_ms,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                estimated_cost_usd=usage.estimated_cost_usd,
                result_metadata={
                    "is_complete": result.is_complete,
                    "completion_reason": result.completion_reason,
                    "follow_up_number": follow_up_count,
                    "missing_fields": result.missing_fields,
                    "category": result.extracted_data.categoria_preliminar,
                    "district": result.extracted_data.distrito,
                    "relation": result.extracted_data.relacion_incidente,
                    "place_type": result.extracted_data.tipo_lugar,
                    "incident_datetime": result.extracted_data.incident_datetime,
                    "incident_datetime_precision": (
                        result.extracted_data.incident_datetime_precision
                    ),
                    "is_recurring": result.extracted_data.is_recurring,
                    "recurrence_pattern": result.extracted_data.recurrence_pattern,
                    "requires_human_review": result.requires_human_review,
                    "emergency_guidance": result.emergency_guidance,
                },
            )
        )
        self.db.commit()
        self.db.refresh(session)
        return self.to_response(session)

    def submit(self, session_id: str, payload: IntakeSubmissionRequest):
        return self._submit(
            session_id,
            name=payload.name,
            identification=payload.identification,
            email=payload.email,
            phone=payload.phone,
            truth_confirmation=payload.truth_confirmation,
            data_usage_consent=payload.data_usage_consent,
            source="persistent_intake",
        )

    def submit_internal(self, session_id: str, payload: InternalIntakeSubmissionRequest):
        incident = self._submit(
            session_id,
            truth_confirmation=payload.truth_confirmation,
            data_usage_consent=payload.data_usage_consent,
            police_input=True,
            entered_by_badge=payload.entered_by_badge,
            source="internal_intake",
        )
        self.db.add(
            AuditEvent(
                trace_id=str(uuid.uuid4()),
                actor_role="admin",
                action="incident:internal_create",
                resource_type="incident",
                resource_id=str(incident.id),
                details={
                    "police_input": True,
                    "entered_by_badge": payload.entered_by_badge,
                },
            )
        )
        self.db.commit()
        self.db.refresh(incident)
        return incident

    def _submit(
        self,
        session_id: str,
        *,
        truth_confirmation: bool,
        data_usage_consent: bool,
        name: str | None = None,
        identification: str | None = None,
        email: str | None = None,
        phone: str | None = None,
        police_input: bool = False,
        entered_by_badge: str | None = None,
        source: str = "persistent_intake",
    ):
        session = self.db.scalar(
            select(IntakeSession)
            .where(IntakeSession.id == session_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if session is None:
            raise IntakeSessionNotFoundError(session_id)
        if session.submitted_at is not None:
            raise IncompleteIntakeError("La sesión ya fue enviada; inicie un nuevo reporte.")
        response = self.to_response(session)
        if not session.is_complete:
            raise IncompleteIntakeError(
                "La denuncia aún no está lista. Continúe la conversación o indique "
                "explícitamente que desea enviarla con la información disponible."
            )
        workflow = session.extracted_data.get("_workflow", {})
        is_anonymous = session.registration_mode == "anonymous"
        extracted = dict(session.extracted_data)
        extracted.pop("_workflow", None)
        incident_payload = ComplaintSubmissionCreate(
            name=None if is_anonymous else name,
            identification=None if is_anonymous else identification,
            email=None if is_anonymous else email,
            phone=None if is_anonymous else phone,
            entered_by_badge=entered_by_badge,
            ai_extracted_data=ComplaintExtractedData.model_validate(extracted),
            ai_summary_text=session.summary_text,
            analysis_metadata={
                "source": source,
                "session_id": session.id,
                "registration_mode": session.registration_mode,
                "anonymous": is_anonymous,
                "confidence_by_field": (
                    response.extracted_data.confidence_by_field.model_dump(exclude_none=True)
                ),
                "field_states": response.extracted_data.field_states.model_dump(),
                "missing_operational_fields": workflow.get("unresolved_fields", []),
                "completion_reason": workflow.get("completion_reason"),
                "follow_up_count": workflow.get("follow_up_count", 0),
                "emergency_guidance_shown": workflow.get("emergency_guidance_shown", False),
            },
            requires_human_review=bool(workflow.get("requires_human_review")),
            review_reason=workflow.get("review_reason"),
            model_name=session.model_name,
            prompt_version=session.prompt_version,
            truth_confirmation=truth_confirmation,
            data_usage_consent=data_usage_consent,
            police_input=police_input,
        )
        # The existing row lock and this marker commit with the initial incident,
        # before any external AI work releases the transaction.
        session.submitted_at = datetime.now(UTC)
        incident = IncidentService(self.db).create(
            incident_payload,
            process_semantic=self.process_semantic,
        )
        session.submitted_incident_id = incident.id
        self.db.commit()
        return incident

    def to_response(self, session: IntakeSession) -> IntakeSessionResponse:
        extracted = dict(session.extracted_data or {})
        workflow = extracted.pop("_workflow", {})
        data = reconcile_field_states(ComplaintExtractedData.model_validate(extracted))
        missing = actionable_missing_fields(data)
        return IntakeSessionResponse(
            session_id=session.id,
            registration_mode=session.registration_mode,
            messages=[ChatMessage.model_validate(message) for message in session.messages],
            is_complete=session.is_complete,
            missing_fields=missing,
            extracted_data=data,
            summary_text=session.summary_text,
            requires_human_review=bool(workflow.get("requires_human_review")),
            review_reason=workflow.get("review_reason"),
            emergency_guidance_shown=bool(workflow.get("emergency_guidance_shown")),
            user_wants_to_finish=bool(workflow.get("user_wants_to_finish")),
            completion_reason=workflow.get("completion_reason", "needs_follow_up"),
            follow_up_count=int(workflow.get("follow_up_count", 0)),
            model_name=session.model_name,
            prompt_version=session.prompt_version,
            trace_id=session.last_trace_id,
        )
