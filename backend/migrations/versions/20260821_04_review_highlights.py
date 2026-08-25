"""Separate operational highlights from data-quality reviews."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260821_04"
down_revision: str | None = "20260814_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _json_type(bind):
    if bind.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import JSONB

        return JSONB()
    return sa.JSON()


def upgrade() -> None:
    bind = op.get_bind()
    json_type = _json_type(bind)
    op.add_column(
        "human_reviews",
        sa.Column(
            "review_type",
            sa.String(64),
            nullable=False,
            server_default="data_quality",
        ),
    )
    op.add_column("human_reviews", sa.Column("ai_summary", sa.Text(), nullable=True))
    op.add_column(
        "human_reviews",
        sa.Column("quality_issues", json_type, nullable=False, server_default="[]"),
    )
    op.add_column(
        "human_reviews",
        sa.Column("recommended_actions", json_type, nullable=False, server_default="[]"),
    )
    op.add_column(
        "human_reviews",
        sa.Column(
            "contact_available",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "human_reviews",
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "incident_highlights",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "incident_id",
            sa.Integer(),
            sa.ForeignKey("complaint_submissions.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("attention_level", sa.String(32), nullable=False),
        sa.Column("reasons", json_type, nullable=False, server_default="[]"),
        sa.Column("ai_summary", sa.Text(), nullable=False),
        sa.Column("recommended_precautions", json_type, nullable=False, server_default="[]"),
        sa.Column("evidence", json_type, nullable=False, server_default="[]"),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("resolution_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_incident_highlights_incident_id",
        "incident_highlights",
        ["incident_id"],
        unique=True,
    )
    op.create_index(
        "ix_incident_highlights_status", "incident_highlights", ["status"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_incident_highlights_status", table_name="incident_highlights")
    op.drop_index("ix_incident_highlights_incident_id", table_name="incident_highlights")
    op.drop_table("incident_highlights")
    op.drop_column("human_reviews", "updated_at")
    op.drop_column("human_reviews", "contact_available")
    op.drop_column("human_reviews", "recommended_actions")
    op.drop_column("human_reviews", "quality_issues")
    op.drop_column("human_reviews", "ai_summary")
    op.drop_column("human_reviews", "review_type")
