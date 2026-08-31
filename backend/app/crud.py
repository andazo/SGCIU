from sqlalchemy.orm import Session

from .models import ComplaintSubmission, FormSubmission
from .schemas import ComplaintSubmissionCreate, FormSubmissionCreate


def create_form_submission(db: Session, payload: FormSubmissionCreate):
    row = FormSubmission(
        name=payload.name,
        email=payload.email,
        message=payload.message,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def list_form_submissions(db: Session):
    return db.query(FormSubmission).order_by(FormSubmission.created_at.desc()).all()


def create_complaint_submission(db: Session, payload: ComplaintSubmissionCreate):
    row = ComplaintSubmission(
        name=payload.name,
        identification=payload.identification,
        entered_by_badge=payload.entered_by_badge,
        email=str(payload.email) if payload.email else None,
        phone=payload.phone,
        ai_extracted_data=payload.ai_extracted_data.model_dump(),
        ai_summary_text=payload.ai_summary_text,
        analysis_metadata=payload.analysis_metadata,
        police_input=payload.police_input,
        requires_human_review=payload.requires_human_review,
        review_reason=payload.review_reason,
        model_name=payload.model_name,
        prompt_version=payload.prompt_version,
        truth_confirmation=payload.truth_confirmation,
        data_usage_consent=payload.data_usage_consent,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def list_complaint_submissions(db: Session):
    return db.query(ComplaintSubmission).order_by(ComplaintSubmission.created_at.desc()).all()
