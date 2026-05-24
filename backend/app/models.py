from sqlalchemy import Boolean, Column, Integer, String, Text, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from .db import Base

class FormSubmission(Base):
    __tablename__ = "form_submissions"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), nullable=False)
    email = Column(String(120), nullable=False, index=True)
    message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ComplaintSubmission(Base):
    __tablename__ = "complaint_submissions"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), nullable=True)
    email = Column(String(120), nullable=True, index=True)
    phone = Column(String(40), nullable=True)
    ai_extracted_data = Column(JSONB, nullable=False)
    truth_confirmation = Column(Boolean, nullable=False)
    data_usage_consent = Column(Boolean, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
