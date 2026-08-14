from __future__ import annotations

import uuid

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

try:
    from pgvector.sqlalchemy import Vector
except ImportError:  # Allows static analysis before optional dependencies are installed.
    Vector = None

from .config import get_settings
from .db import Base

JSON_TYPE = JSON().with_variant(JSONB(), "postgresql")


def _vector_type():
    if Vector is None:
        return JSON_TYPE
    return Vector(get_settings().embedding_dimensions).with_variant(JSON(), "sqlite")

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
    ai_extracted_data = Column(JSON_TYPE, nullable=False)
    ai_summary_text = Column(Text, nullable=True)
    analysis_metadata = Column(JSON_TYPE, nullable=False, default=dict)
    status = Column(String(32), nullable=False, default="submitted", index=True)
    requires_human_review = Column(Boolean, nullable=False, default=False)
    review_reason = Column(Text, nullable=True)
    model_name = Column(String(120), nullable=True)
    prompt_version = Column(String(40), nullable=True)
    truth_confirmation = Column(Boolean, nullable=False)
    data_usage_consent = Column(Boolean, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    embedding_record = relationship(
        "IncidentEmbedding", back_populates="incident", uselist=False
    )
    cluster_memberships = relationship(
        "IncidentClusterMember", back_populates="incident"
    )


class IntakeSession(Base):
    __tablename__ = "intake_sessions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    messages = Column(JSON_TYPE, nullable=False, default=list)
    extracted_data = Column(JSON_TYPE, nullable=False, default=dict)
    summary_text = Column(Text, nullable=True)
    is_complete = Column(Boolean, nullable=False, default=False)
    model_name = Column(String(120), nullable=True)
    prompt_version = Column(String(40), nullable=False, default="intake-v1")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class IncidentEmbedding(Base):
    __tablename__ = "incident_embeddings"

    id = Column(Integer, primary_key=True)
    incident_id = Column(
        Integer, ForeignKey("complaint_submissions.id", ondelete="CASCADE"), unique=True
    )
    canonical_text = Column(Text, nullable=False)
    embedding = Column(_vector_type(), nullable=False)
    embedding_model = Column(String(120), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    incident = relationship("ComplaintSubmission", back_populates="embedding_record")


class IncidentCluster(Base):
    __tablename__ = "incident_clusters"

    id = Column(Integer, primary_key=True)
    label = Column(String(200), nullable=False)
    status = Column(String(32), nullable=False, default="candidate")
    explanation = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    members = relationship(
        "IncidentClusterMember", back_populates="cluster", cascade="all, delete-orphan"
    )


class IncidentClusterMember(Base):
    __tablename__ = "incident_cluster_members"
    __table_args__ = (UniqueConstraint("cluster_id", "incident_id"),)

    id = Column(Integer, primary_key=True)
    cluster_id = Column(
        Integer, ForeignKey("incident_clusters.id", ondelete="CASCADE"), index=True
    )
    incident_id = Column(
        Integer, ForeignKey("complaint_submissions.id", ondelete="CASCADE"), index=True
    )
    similarity_score = Column(Float, nullable=False)
    match_reason = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    cluster = relationship("IncidentCluster", back_populates="members")
    incident = relationship("ComplaintSubmission", back_populates="cluster_memberships")


class HumanReview(Base):
    __tablename__ = "human_reviews"

    id = Column(Integer, primary_key=True)
    incident_id = Column(
        Integer, ForeignKey("complaint_submissions.id", ondelete="CASCADE"), index=True
    )
    reason = Column(Text, nullable=False)
    status = Column(String(32), nullable=False, default="pending", index=True)
    resolution_notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    resolved_at = Column(DateTime(timezone=True), nullable=True)


class AssistantFeedback(Base):
    __tablename__ = "assistant_feedback"

    id = Column(Integer, primary_key=True)
    trace_id = Column(String(36), nullable=False, index=True)
    actor_role = Column(String(32), nullable=False)
    rating = Column(Integer, nullable=False)
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id = Column(Integer, primary_key=True)
    trace_id = Column(String(36), nullable=False, index=True)
    actor_role = Column(String(32), nullable=False)
    action = Column(String(120), nullable=False, index=True)
    resource_type = Column(String(80), nullable=False)
    resource_id = Column(String(80), nullable=True)
    details = Column(JSON_TYPE, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
