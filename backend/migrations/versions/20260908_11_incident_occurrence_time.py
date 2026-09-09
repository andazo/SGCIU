"""Store the normalized occurrence time used by semantic analysis."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260908_11"
down_revision: str | None = "20260907_10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    json_type = sa.JSON()
    if bind.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import JSONB

        json_type = JSONB()

    op.add_column(
        "complaint_submissions",
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "complaint_submissions",
        sa.Column(
            "occurred_at_precision",
            sa.String(length=24),
            nullable=False,
            server_default="unknown",
        ),
    )
    op.add_column(
        "complaint_submissions",
        sa.Column(
            "occurred_at_source",
            sa.String(length=24),
            nullable=False,
            server_default="unknown",
        ),
    )
    op.create_index(
        "ix_complaint_submissions_occurred_at",
        "complaint_submissions",
        ["occurred_at"],
    )

    if bind.dialect.name == "postgresql":
        op.execute(
            sa.text(
                """
                UPDATE complaint_submissions
                SET occurred_at = (ai_extracted_data->>'incident_datetime')::timestamptz,
                    occurred_at_precision = COALESCE(
                        NULLIF(ai_extracted_data->>'incident_datetime_precision', ''),
                        'unknown'
                    ),
                    occurred_at_source = COALESCE(
                        NULLIF(ai_extracted_data->>'incident_datetime_source', ''),
                        'explicit'
                    )
                WHERE ai_extracted_data->>'incident_datetime'
                    ~ '^20[0-9]{2}-[0-9]{2}-[0-9]{2}T'
                """
            )
        )
        op.execute(
            sa.text(
                "CREATE INDEX IF NOT EXISTS ix_incident_location_embeddings_hnsw "
                "ON incident_embeddings USING hnsw "
                "(location_embedding vector_cosine_ops)"
            )
        )
    op.add_column(
        "intake_sessions",
        sa.Column("last_trace_id", sa.String(length=36), nullable=True),
    )
    op.create_index("ix_intake_sessions_last_trace_id", "intake_sessions", ["last_trace_id"])
    op.add_column(
        "legal_query_traces",
        sa.Column(
            "retrieved_chunk_ids",
            json_type,
            nullable=False,
            server_default=sa.text("'[]'" if bind.dialect.name != "postgresql" else "'[]'::jsonb"),
        ),
    )
    if bind.dialect.name == "postgresql":
        op.execute(
            sa.text(
                "CREATE INDEX ix_legal_chunks_content_fts ON legal_chunks "
                "USING gin (to_tsvector('spanish'::regconfig, content))"
            )
        )
    op.create_table(
        "ai_interaction_traces",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("trace_id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=True),
        sa.Column("incident_id", sa.Integer(), nullable=True),
        sa.Column("feature", sa.String(length=64), nullable=False),
        sa.Column("model_name", sa.String(length=120), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("estimated_cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("result_metadata", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_ai_interaction_traces_trace_id",
        "ai_interaction_traces",
        ["trace_id"],
        unique=True,
    )
    op.create_index("ix_ai_interaction_traces_session_id", "ai_interaction_traces", ["session_id"])
    op.create_index(
        "ix_ai_interaction_traces_incident_id", "ai_interaction_traces", ["incident_id"]
    )
    op.create_index("ix_ai_interaction_traces_feature", "ai_interaction_traces", ["feature"])
    op.create_index("ix_ai_interaction_traces_created_at", "ai_interaction_traces", ["created_at"])
    op.create_table(
        "manual_evaluation_labels",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("trace_id", sa.String(length=36), nullable=False),
        sa.Column("expected_output", json_type, nullable=False),
        sa.Column("quality_scores", json_type, nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_manual_evaluation_labels_trace_id",
        "manual_evaluation_labels",
        ["trace_id"],
        unique=True,
    )


def downgrade() -> None:
    bind = op.get_bind()
    op.drop_index("ix_manual_evaluation_labels_trace_id", table_name="manual_evaluation_labels")
    op.drop_table("manual_evaluation_labels")
    op.drop_index("ix_ai_interaction_traces_created_at", table_name="ai_interaction_traces")
    op.drop_index("ix_ai_interaction_traces_feature", table_name="ai_interaction_traces")
    op.drop_index("ix_ai_interaction_traces_incident_id", table_name="ai_interaction_traces")
    op.drop_index("ix_ai_interaction_traces_session_id", table_name="ai_interaction_traces")
    op.drop_index("ix_ai_interaction_traces_trace_id", table_name="ai_interaction_traces")
    op.drop_table("ai_interaction_traces")
    if bind.dialect.name == "postgresql":
        op.execute(sa.text("DROP INDEX IF EXISTS ix_legal_chunks_content_fts"))
        op.execute(sa.text("DROP INDEX IF EXISTS ix_incident_location_embeddings_hnsw"))
    op.drop_column("legal_query_traces", "retrieved_chunk_ids")
    op.drop_index("ix_intake_sessions_last_trace_id", table_name="intake_sessions")
    op.drop_column("intake_sessions", "last_trace_id")
    op.drop_index(
        "ix_complaint_submissions_occurred_at",
        table_name="complaint_submissions",
    )
    op.drop_column("complaint_submissions", "occurred_at_source")
    op.drop_column("complaint_submissions", "occurred_at_precision")
    op.drop_column("complaint_submissions", "occurred_at")
