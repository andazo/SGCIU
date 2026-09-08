"""Persist reproducible module evaluation reports."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260907_10"
down_revision: str | None = "20260901_09"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _json_type(bind):
    if bind.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import JSONB

        return JSONB()
    return sa.JSON()


def upgrade() -> None:
    bind = op.get_bind()
    op.create_table(
        "evaluation_runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("module", sa.String(length=64), nullable=False),
        sa.Column("dataset_name", sa.String(length=160), nullable=False),
        sa.Column("dataset_version", sa.String(length=64), nullable=False),
        sa.Column("dataset_sha256", sa.String(length=64), nullable=False),
        sa.Column("environment", sa.String(length=32), nullable=False),
        sa.Column("model_configuration", _json_type(bind), nullable=False),
        sa.Column("metrics", _json_type(bind), nullable=False),
        sa.Column("case_results", _json_type(bind), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_evaluation_runs_module", "evaluation_runs", ["module"])


def downgrade() -> None:
    op.drop_index("ix_evaluation_runs_module", table_name="evaluation_runs")
    op.drop_table("evaluation_runs")
