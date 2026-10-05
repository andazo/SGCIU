from sqlalchemy.orm import Session

from .models import ComplaintSubmission, FormSubmission
from .schemas import FormSubmissionCreate


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


def list_complaint_submissions(db: Session):
    return db.query(ComplaintSubmission).order_by(ComplaintSubmission.created_at.desc()).all()
