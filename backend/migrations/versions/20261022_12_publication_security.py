"""Isolate session ownership and persist shared request quotas."""

import sqlalchemy as sa
from alembic import op

revision = "20261022_12"
down_revision = "20260908_11"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("intake_sessions", sa.Column("access_token_hash", sa.String(64)))
    op.add_column(
        "intake_sessions",
        sa.Column("audience", sa.String(16), nullable=False, server_default="legacy"),
    )
    # Nullable columns leave existing records intact; legacy sessions fail closed at HTTP routes.
    op.add_column("intake_sessions", sa.Column("owner_user_id", sa.Integer()))
    op.add_column("intake_sessions", sa.Column("submitted_incident_id", sa.Integer()))
    op.add_column("intake_sessions", sa.Column("submitted_at", sa.DateTime(timezone=True)))
    op.add_column("operational_sessions", sa.Column("owner_user_id", sa.Integer()))
    op.create_table(
        "security_request_buckets",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.BigInteger(), nullable=False, index=True),
    )


def downgrade():
    op.drop_table("security_request_buckets")
    op.drop_column("operational_sessions", "owner_user_id")
    for name in (
        "submitted_at",
        "submitted_incident_id",
        "owner_user_id",
        "audience",
        "access_token_hash",
    ):
        op.drop_column("intake_sessions", name)
