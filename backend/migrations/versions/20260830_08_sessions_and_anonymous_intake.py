"""Persist intake modes and administrative assistant sessions."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "20260830_08"
down_revision: str | None = "20260828_07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _json_type(bind):
    if bind.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import JSONB

        return JSONB()
    return sa.JSON()


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns("intake_sessions")}
    if "registration_mode" not in columns:
        op.add_column(
            "intake_sessions",
            sa.Column(
                "registration_mode",
                sa.String(length=16),
                nullable=False,
                server_default="complete",
            ),
        )
    tables = set(inspect(bind).get_table_names())
    if "operational_sessions" not in tables:
        op.create_table(
            "operational_sessions",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("messages", _json_type(bind), nullable=False, server_default="[]"),
            sa.Column("model_name", sa.String(length=120), nullable=True),
            sa.Column(
                "prompt_version",
                sa.String(length=40),
                nullable=False,
                server_default="operational-react-v5",
            ),
            sa.Column("last_trace_id", sa.String(length=36), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index(
            "ix_operational_sessions_last_trace_id",
            "operational_sessions",
            ["last_trace_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    if "operational_sessions" in inspect(bind).get_table_names():
        op.drop_index("ix_operational_sessions_last_trace_id", table_name="operational_sessions")
        op.drop_table("operational_sessions")
    columns = {column["name"] for column in inspect(bind).get_columns("intake_sessions")}
    if "registration_mode" in columns:
        op.drop_column("intake_sessions", "registration_mode")
