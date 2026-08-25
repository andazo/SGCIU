"""Add the versioned legal corpus and RAG audit schema."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260824_05"
down_revision: str | None = "20260821_04"
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


def upgrade() -> None:
    bind = op.get_bind()
    json_type = _json_type(bind)
    op.create_table(
        "legal_documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_key", sa.String(160), nullable=False, unique=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("short_title", sa.String(240), nullable=False),
        sa.Column("source_filename", sa.String(300), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("authority", sa.String(240), nullable=False),
        sa.Column("jurisdiction", sa.String(120), nullable=False),
        sa.Column("document_type", sa.String(80), nullable=False),
        sa.Column("corpus_version", sa.String(40), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("metadata", json_type, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_legal_documents_document_key", "legal_documents", ["document_key"])
    op.create_index("ix_legal_documents_corpus_version", "legal_documents", ["corpus_version"])
    op.create_index("ix_legal_documents_status", "legal_documents", ["status"])
    op.create_table(
        "legal_chunks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "document_id",
            sa.Integer(),
            sa.ForeignKey("legal_documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("printed_page_label", sa.String(32), nullable=True),
        sa.Column("section_path", sa.String(500), nullable=True),
        sa.Column("article_references", json_type, nullable=False, server_default="[]"),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("estimated_tokens", sa.Integer(), nullable=False),
        sa.Column("embedding", _vector_type(bind), nullable=False),
        sa.Column("embedding_model", sa.String(120), nullable=False),
        sa.Column("corpus_version", sa.String(40), nullable=False),
        sa.Column("metadata", json_type, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("document_id", "chunk_index"),
    )
    op.create_index("ix_legal_chunks_document_id", "legal_chunks", ["document_id"])
    op.create_index("ix_legal_chunks_page_number", "legal_chunks", ["page_number"])
    op.create_index("ix_legal_chunks_content_hash", "legal_chunks", ["content_hash"])
    op.create_index("ix_legal_chunks_corpus_version", "legal_chunks", ["corpus_version"])
    if bind.dialect.name == "postgresql":
        op.execute(
            "CREATE INDEX ix_legal_chunks_embedding_hnsw ON legal_chunks "
            "USING hnsw (embedding vector_cosine_ops)"
        )
        op.execute(
            "CREATE INDEX ix_legal_chunks_content_fts ON legal_chunks "
            "USING gin (to_tsvector('spanish', content))"
        )
    op.create_table(
        "legal_query_traces",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("trace_id", sa.String(36), nullable=False, unique=True),
        sa.Column("query_hash", sa.String(64), nullable=False),
        sa.Column("cited_chunk_ids", json_type, nullable=False, server_default="[]"),
        sa.Column("retrieved_embeddings", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("indexed_embeddings", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("model_name", sa.String(120), nullable=False),
        sa.Column("embedding_model", sa.String(120), nullable=False),
        sa.Column("prompt_version", sa.String(40), nullable=False),
        sa.Column("corpus_version", sa.String(40), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Float(), nullable=False, server_default="0"),
        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("error_type", sa.String(120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_legal_query_traces_trace_id", "legal_query_traces", ["trace_id"])


def downgrade() -> None:
    op.drop_index("ix_legal_query_traces_trace_id", table_name="legal_query_traces")
    op.drop_table("legal_query_traces")
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_legal_chunks_content_fts")
        op.execute("DROP INDEX IF EXISTS ix_legal_chunks_embedding_hnsw")
    op.drop_index("ix_legal_chunks_corpus_version", table_name="legal_chunks")
    op.drop_index("ix_legal_chunks_content_hash", table_name="legal_chunks")
    op.drop_index("ix_legal_chunks_page_number", table_name="legal_chunks")
    op.drop_index("ix_legal_chunks_document_id", table_name="legal_chunks")
    op.drop_table("legal_chunks")
    op.drop_index("ix_legal_documents_status", table_name="legal_documents")
    op.drop_index("ix_legal_documents_corpus_version", table_name="legal_documents")
    op.drop_index("ix_legal_documents_document_key", table_name="legal_documents")
    op.drop_table("legal_documents")
