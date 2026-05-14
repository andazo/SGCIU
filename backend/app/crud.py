from sqlalchemy.orm import Session
from .models import FormSubmission
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
