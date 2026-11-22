"""Milestone 3: add ai_research_messages for research session context.

Revision ID: 002_research_session_messages
Revises: 001_initial_ai_service_tables
Create Date: 2026-11-21 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "002_research_session_messages"
down_revision = "001_initial_ai_service_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_research_messages",
        sa.Column("message_id", sa.String(64), primary_key=True),
        sa.Column("session_id", sa.String(64), nullable=False),
        sa.Column("document_id", sa.String(64), nullable=True),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("citations", postgresql.JSONB(astext_type=sa.Text()), server_default="[]"),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), server_default="{}"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "idx_ai_research_messages_session",
        "ai_research_messages",
        ["session_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_ai_research_messages_session", table_name="ai_research_messages")
    op.drop_table("ai_research_messages")
