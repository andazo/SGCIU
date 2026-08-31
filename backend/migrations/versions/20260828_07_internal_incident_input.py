"""Add provenance fields for incidents entered by municipal personnel."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "20260828_07"
down_revision: str | None = "20260826_06"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns("complaint_submissions")}
    if "entered_by_badge" not in columns:
        op.add_column(
            "complaint_submissions",
            sa.Column("entered_by_badge", sa.String(length=64), nullable=True),
        )
    if "police_input" not in columns:
        op.add_column(
            "complaint_submissions",
            sa.Column(
                "police_input",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns("complaint_submissions")}
    if "police_input" in columns:
        op.drop_column("complaint_submissions", "police_input")
    if "entered_by_badge" in columns:
        op.drop_column("complaint_submissions", "entered_by_badge")
