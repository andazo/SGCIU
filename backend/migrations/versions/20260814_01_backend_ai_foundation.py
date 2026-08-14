"""Create the backend AI foundation schema."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "20260814_01"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _json_type(bind):
    if bind.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import JSONB

        return JSONB()
    return sa.JSON()


def _vector_type(bind):
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
        from pgvector.sqlalchemy import Vector

        return Vector(1536)
    return sa.JSON()


def _add_missing_complaint_columns(bind) -> None:
    columns = {column["name"] for column in inspect(bind).get_columns("complaint_submissions")}
    additions = {
        "ai_summary_text": sa.Column("ai_summary_text", sa.Text(), nullable=True),
        "analysis_metadata": sa.Column(
            "analysis_metadata", _json_type(bind), nullable=False, server_default="{}"
        ),
        "status": sa.Column("status", sa.String(32), nullable=False, server_default="submitted"),
        "requires_human_review": sa.Column(
            "requires_human_review", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        "review_reason": sa.Column("review_reason", sa.Text(), nullable=True),
        "model_name": sa.Column("model_name", sa.String(120), nullable=True),
        "prompt_version": sa.Column("prompt_version", sa.String(40), nullable=True),
        "updated_at": sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    }
    for name, column in additions.items():
        if name not in columns:
            op.add_column("complaint_submissions", column)


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())
    json_type = _json_type(bind)

    if "form_submissions" not in tables:
        op.create_table(
            "form_submissions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(120), nullable=False),
            sa.Column("email", sa.String(120), nullable=False),
            sa.Column("message", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )

    if "complaint_submissions" not in tables:
        op.create_table(
            "complaint_submissions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(120), nullable=True),
            sa.Column("email", sa.String(120), nullable=True),
            sa.Column("phone", sa.String(40), nullable=True),
            sa.Column("ai_extracted_data", json_type, nullable=False),
            sa.Column("ai_summary_text", sa.Text(), nullable=True),
            sa.Column("analysis_metadata", json_type, nullable=False, server_default="{}"),
            sa.Column("status", sa.String(32), nullable=False, server_default="submitted"),
            sa.Column(
                "requires_human_review", sa.Boolean(), nullable=False, server_default=sa.false()
            ),
            sa.Column("review_reason", sa.Text(), nullable=True),
            sa.Column("model_name", sa.String(120), nullable=True),
            sa.Column("prompt_version", sa.String(40), nullable=True),
            sa.Column("truth_confirmation", sa.Boolean(), nullable=False),
            sa.Column("data_usage_consent", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    else:
        _add_missing_complaint_columns(bind)

    op.create_table(
        "intake_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("messages", json_type, nullable=False),
        sa.Column("extracted_data", json_type, nullable=False),
        sa.Column("summary_text", sa.Text(), nullable=True),
        sa.Column("is_complete", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("model_name", sa.String(120), nullable=True),
        sa.Column("prompt_version", sa.String(40), nullable=False, server_default="intake-v1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "incident_embeddings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "incident_id",
            sa.Integer(),
            sa.ForeignKey("complaint_submissions.id", ondelete="CASCADE"),
            unique=True,
        ),
        sa.Column("canonical_text", sa.Text(), nullable=False),
        sa.Column("embedding", _vector_type(bind), nullable=False),
        sa.Column("embedding_model", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "incident_clusters",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="candidate"),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "incident_cluster_members",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "cluster_id", sa.Integer(), sa.ForeignKey("incident_clusters.id", ondelete="CASCADE")
        ),
        sa.Column(
            "incident_id",
            sa.Integer(),
            sa.ForeignKey("complaint_submissions.id", ondelete="CASCADE"),
        ),
        sa.Column("similarity_score", sa.Float(), nullable=False),
        sa.Column("match_reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("cluster_id", "incident_id"),
    )
    op.create_table(
        "human_reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "incident_id",
            sa.Integer(),
            sa.ForeignKey("complaint_submissions.id", ondelete="CASCADE"),
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("resolution_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "assistant_feedback",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("trace_id", sa.String(36), nullable=False),
        sa.Column("actor_role", sa.String(32), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("trace_id", sa.String(36), nullable=False),
        sa.Column("actor_role", sa.String(32), nullable=False),
        sa.Column("action", sa.String(120), nullable=False),
        sa.Column("resource_type", sa.String(80), nullable=False),
        sa.Column("resource_id", sa.String(80), nullable=True),
        sa.Column("details", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    for table in (
        "audit_events",
        "assistant_feedback",
        "human_reviews",
        "incident_cluster_members",
        "incident_clusters",
        "incident_embeddings",
        "intake_sessions",
    ):
        op.drop_table(table)
