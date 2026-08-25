"""Add optional citizen identification to complaint submissions."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "20260814_03"
down_revision: str | None = "20260814_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {
        column["name"] for column in inspect(bind).get_columns("complaint_submissions")
    }
    if "identification" not in columns:
        op.add_column(
            "complaint_submissions",
            sa.Column("identification", sa.String(length=64), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    columns = {
        column["name"] for column in inspect(bind).get_columns("complaint_submissions")
    }
    if "identification" in columns:
        op.drop_column("complaint_submissions", "identification")
