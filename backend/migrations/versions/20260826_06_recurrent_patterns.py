"""Store a dedicated semantic embedding for incident locations."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260826_06"
down_revision: str | None = "20260824_05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        from pgvector.sqlalchemy import Vector

        column_type = Vector(1536)
    else:
        column_type = sa.JSON()
    op.add_column(
        "incident_embeddings",
        sa.Column("location_embedding", column_type, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("incident_embeddings", "location_embedding")
