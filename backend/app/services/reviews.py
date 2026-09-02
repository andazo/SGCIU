from __future__ import annotations

import logging
import re
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.incident_assessment import (
    ASSESSMENT_PROMPT_VERSION,
    IncidentAssessment,
    IncidentAssessmentProvider,
    get_incident_assessment_provider,
)
from app.models import AssistantFeedback, ComplaintSubmission, HumanReview, IncidentHighlight
from app.schemas import ComplaintExtractedData

logger = logging.getLogger(__name__)


class ReviewNotFoundError(LookupError):
    pass


class HighlightNotFoundError(LookupError):
    pass


ACTIVE_WORKFLOW_STATUSES = ("pending", "in_review", "escalated")
HIGHLIGHT_CANDIDATE_CATEGORIES = {
    "violencia",
    "venta_drogas",
    "acoso_o_amenaza",
    "animal_peligroso",
}
RISK_PATTERN = re.compile(
    r"\b(?:arma|pistola|rev[oó]lver|cuchillo|disparo|balacera|pelea|golpe|"
    r"agredi|amenaz|forceje|robo violento|asalto)\w*\b",
    re.IGNORECASE,
)


class ReviewService:
    def __init__(
        self,
        db: Session,
        provider: IncidentAssessmentProvider | None = None,
    ):
        self.db = db
        self.provider = provider

    def list(self, status: str | None = "pending") -> list[HumanReview]:
        query = select(HumanReview).order_by(HumanReview.created_at.desc())
        if status:
            query = query.where(HumanReview.status == status)
        return list(self.db.scalars(query))

    def list_active(self) -> list[HumanReview]:
        return list(
            self.db.scalars(
                select(HumanReview)
                .where(HumanReview.status.in_(ACTIVE_WORKFLOW_STATUSES))
                .order_by(HumanReview.created_at.desc())
            )
        )

    def list_highlights(self, status: str | None = None) -> list[IncidentHighlight]:
        query = select(IncidentHighlight).order_by(IncidentHighlight.created_at.desc())
        if status:
            query = query.where(IncidentHighlight.status == status)
        return list(self.db.scalars(query))

    def list_active_highlights(self) -> list[IncidentHighlight]:
        return list(
            self.db.scalars(
                select(IncidentHighlight)
                .where(IncidentHighlight.status.in_(ACTIVE_WORKFLOW_STATUSES))
                .order_by(IncidentHighlight.created_at.desc())
            )
        )

    def request_quality_review(
        self,
        incident: ComplaintSubmission,
        reason: str,
        *,
        review_type: str = "data_quality",
        ai_summary: str | None = None,
        quality_issues: list[str] | None = None,
        recommended_actions: list[dict[str, str]] | None = None,
    ) -> tuple[HumanReview, bool]:
        existing = self.db.scalar(
            select(HumanReview).where(
                HumanReview.incident_id == incident.id,
                HumanReview.status.in_(ACTIVE_WORKFLOW_STATUSES),
            )
        )
        incident.requires_human_review = True
        incident.review_reason = reason
        incident.status = "under_review"
        values = {
            "reason": reason,
            "review_type": review_type,
            "ai_summary": ai_summary or f"La denuncia requiere validación: {reason}",
            "quality_issues": quality_issues or [reason],
            "recommended_actions": recommended_actions or self._default_actions(incident, reason),
            "contact_available": self._contact_available(incident),
        }
        if existing:
            for field, value in values.items():
                setattr(existing, field, value)
            self.db.commit()
            self.db.refresh(existing)
            return existing, False
        review = HumanReview(incident_id=incident.id, **values)
        self.db.add(review)
        self.db.commit()
        self.db.refresh(review)
        return review, True

    def assess_incident(
        self,
        incident: ComplaintSubmission,
        *,
        initial_quality_reason: str | None = None,
    ) -> IncidentAssessment:
        provider = self.provider or get_incident_assessment_provider()
        self.provider = provider
        assessment = provider.assess(
            ComplaintExtractedData.model_validate(incident.ai_extracted_data),
            incident_summary=incident.ai_summary_text,
            initial_quality_reason=initial_quality_reason,
            contact_available=self._contact_available(incident),
        )
        self._apply_highlight(incident, assessment)
        quality = assessment.quality_review
        quality_reason = (
            initial_quality_reason
            or "; ".join(quality.issues)
            or "La denuncia necesita validación de calidad."
            if quality.required or initial_quality_reason
            else None
        )
        incident.analysis_metadata = {
            **(incident.analysis_metadata or {}),
            "quality_control": {
                "reliability": "limited" if quality_reason else "sufficient",
                "issues": quality.issues,
                "summary": quality.admin_summary,
                "recommended_actions": [
                    action.model_dump() for action in quality.recommended_actions
                ],
                "contact_available": self._contact_available(incident),
            },
        }
        if quality.required or initial_quality_reason:
            reason = quality_reason
            recommended_actions = [
                action.model_dump() for action in quality.recommended_actions
            ]
            contact_available = self._contact_available(incident)
            expected_code = (
                "contact_citizen" if contact_available else "dismiss_if_unrecoverable"
            )
            if not any(action["code"] == expected_code for action in recommended_actions):
                recommended_actions.append(
                    {
                        "code": expected_code,
                        "rationale": (
                            "Existe un medio de contacto para solicitar los datos faltantes."
                            if contact_available
                            else (
                                "No existe contacto; si la revisión del incidente y sus "
                                "relacionados no permite aclararlo, descarte únicamente la "
                                "revisión y conserve la denuncia como información insuficiente."
                            )
                        ),
                    }
                )
            self.request_quality_review(
                incident,
                reason,
                review_type=quality.review_type or "data_quality",
                ai_summary=quality.admin_summary,
                quality_issues=quality.issues or [reason],
                recommended_actions=recommended_actions,
            )
        incident.analysis_metadata = {
            **(incident.analysis_metadata or {}),
            "administrative_assessment_status": "completed",
            "assessment_model": provider.model_name,
            "assessment_prompt_version": ASSESSMENT_PROMPT_VERSION,
            "possible_emergency": assessment.possible_emergency,
            "emergency_reason": assessment.emergency_reason,
        }
        self.db.commit()
        return assessment

    def assess_incident_if_needed(
        self,
        incident: ComplaintSubmission,
        *,
        initial_quality_reason: str | None = None,
    ) -> IncidentAssessment | None:
        data = ComplaintExtractedData.model_validate(incident.ai_extracted_data)
        description = data.descripcion_detallada or ""
        needs_assessment = bool(
            initial_quality_reason
            or data.urgency in {"alta", "inmediata"}
            or data.categoria_preliminar in HIGHLIGHT_CANDIDATE_CATEGORIES
            or RISK_PATTERN.search(description)
        )
        if needs_assessment:
            return self.assess_incident(
                incident,
                initial_quality_reason=initial_quality_reason,
            )
        incident.analysis_metadata = {
            **(incident.analysis_metadata or {}),
            "administrative_assessment_status": "completed",
            "administrative_assessment_result": "no_candidate_signals",
        }
        self.db.commit()
        return None

    def assess_pending_incidents(
        self,
        progress: Callable[[int, int, int], None] | None = None,
    ) -> tuple[int, int, int]:
        incidents = list(self.db.scalars(select(ComplaintSubmission)))
        pending = [
            incident
            for incident in incidents
            if (incident.analysis_metadata or {}).get("administrative_assessment_status")
            != "completed"
        ]
        completed = 0
        failed = 0
        for position, incident in enumerate(pending, start=1):
            try:
                self.assess_incident_if_needed(
                    incident,
                    initial_quality_reason=(
                        incident.review_reason if incident.requires_human_review else None
                    ),
                )
                completed += 1
                if progress:
                    progress(position, len(pending), incident.id)
            except Exception as exc:
                failed += 1
                logger.warning(
                    "Pending administrative assessment failed",
                    extra={
                        "feature": "incident_assessment",
                        "incident_id": incident.id,
                        "error_type": type(exc).__name__,
                    },
                )
                if progress:
                    progress(position, len(pending), incident.id)
        return len(pending), completed, failed

    def _apply_highlight(
        self,
        incident: ComplaintSubmission,
        assessment: IncidentAssessment,
    ) -> IncidentHighlight | None:
        details = assessment.highlight
        if not details.required:
            return None
        highlight = self.db.scalar(
            select(IncidentHighlight).where(IncidentHighlight.incident_id == incident.id)
        )
        values = {
            "attention_level": details.attention_level,
            "reasons": details.reasons,
            "ai_summary": details.operational_summary,
            "recommended_precautions": details.recommended_precautions,
            "evidence": details.evidence,
        }
        if highlight is None:
            highlight = IncidentHighlight(incident_id=incident.id, **values)
            self.db.add(highlight)
        elif highlight.status in ACTIVE_WORKFLOW_STATUSES:
            for field, value in values.items():
                setattr(highlight, field, value)
        self.db.flush()
        return highlight

    def resolve(self, review_id: int, notes: str) -> HumanReview:
        return self.transition_review(review_id, "resolve", notes)

    def transition_review(self, review_id: int, action: str, notes: str) -> HumanReview:
        review = self.db.get(HumanReview, review_id)
        if review is None:
            raise ReviewNotFoundError(review_id)
        statuses = {
            "start": "in_review",
            "resolve": "resolved",
            "dismiss": "dismissed",
            "escalate": "escalated",
        }
        if action not in statuses:
            raise ValueError(f"Acción de revisión no válida: {action}")
        review.status = statuses[action]
        review.resolution_notes = notes
        review.resolved_at = datetime.now(UTC) if action in {"resolve", "dismiss"} else None
        incident = self.db.get(ComplaintSubmission, review.incident_id)
        if incident is None:
            raise ReviewNotFoundError(review_id)
        active_reviews = self.db.scalar(
            select(HumanReview.id).where(
                HumanReview.incident_id == incident.id,
                HumanReview.id != review.id,
                HumanReview.status.in_(ACTIVE_WORKFLOW_STATUSES),
            )
        )
        incident.requires_human_review = action not in {"resolve", "dismiss"} or bool(
            active_reviews
        )
        if action == "dismiss":
            incident.status = "insufficient_information"
        elif action == "resolve" and not active_reviews:
            incident.status = "reviewed"
        else:
            incident.status = "under_review"
        self.db.commit()
        self.db.refresh(review)
        return review

    def transition_highlight(
        self,
        highlight_id: int,
        action: str,
        notes: str,
    ) -> IncidentHighlight:
        highlight = self.db.get(IncidentHighlight, highlight_id)
        if highlight is None:
            raise HighlightNotFoundError(highlight_id)
        statuses = {
            "start": "in_review",
            "resolve": "resolved",
            "escalate": "escalated",
        }
        if action not in statuses:
            raise ValueError(f"Acción de resaltado no válida: {action}")
        highlight.status = statuses[action]
        highlight.resolution_notes = notes
        highlight.resolved_at = datetime.now(UTC) if action == "resolve" else None
        self.db.commit()
        self.db.refresh(highlight)
        return highlight

    @staticmethod
    def _contact_available(incident: ComplaintSubmission) -> bool:
        return bool(incident.email or incident.phone)

    @classmethod
    def _default_actions(
        cls,
        incident: ComplaintSubmission,
        reason: str,
    ) -> list[dict[str, str]]:
        actions = [
            {
                "code": "inspect_incident",
                "rationale": "Verificar el relato y los campos extraídos antes de decidir.",
            }
        ]
        if cls._contact_available(incident):
            actions.append(
                {
                    "code": "contact_citizen",
                    "rationale": "Existe un medio de contacto para solicitar la aclaración.",
                }
            )
        else:
            actions.append(
                {
                    "code": "dismiss_if_unrecoverable",
                    "rationale": (
                        "No hay contacto disponible; descarte únicamente la revisión si "
                        f"no puede resolver el problema con otros incidentes. Motivo: {reason}"
                    ),
                }
            )
        return actions

    def record_feedback(
        self,
        *,
        trace_id: str,
        actor_role: str,
        rating: int,
        comment: str | None,
    ) -> AssistantFeedback:
        feedback = AssistantFeedback(
            trace_id=trace_id,
            actor_role=actor_role,
            rating=rating,
            comment=comment,
        )
        self.db.add(feedback)
        self.db.commit()
        self.db.refresh(feedback)
        return feedback
