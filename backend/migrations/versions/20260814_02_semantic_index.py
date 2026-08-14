"""Add the vector search index used by semantic incident retrieval."""

from collections.abc import Sequence

from alembic import op

revision: str = "20260814_02"
down_revision: str | None = "20260814_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_incident_embeddings_hnsw "
            "ON incident_embeddings USING hnsw (embedding vector_cosine_ops)"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_incident_embeddings_hnsw")
