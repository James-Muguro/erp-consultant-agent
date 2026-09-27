"""add attention_items and erp_user_requests

Revision ID: d4f1a8b2c9e3
Revises: 692e2495ae4e
Create Date: 2026-09-26 14:00:00.000000

Phase 2.5 Step 1 (D3). Unified consultant-inbox routing table plus the
ERP User request source. Both are additive and reversible. No existing
table, column, index, or constraint is modified.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd4f1a8b2c9e3'
down_revision: Union[str, Sequence[str], None] = '692e2495ae4e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "attention_items",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("recipient_user_id", sa.String(), nullable=False),
        sa.Column("organization_id", sa.String(), nullable=True),
        sa.Column("session_id", sa.String(), nullable=True),
        sa.Column("source_type", sa.String(), nullable=False),
        sa.Column("source_id", sa.String(), nullable=False),
        sa.Column(
            "status", sa.String(), nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by_user_id", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["recipient_user_id"], ["users.id"], ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["sessions.session_id"], ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["resolved_by_user_id"], ["users.id"], ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status IN ('pending', 'resolved')",
            name="ck_attention_items_status",
        ),
    )
    op.create_index(
        "ix_attention_items_recipient_user_id",
        "attention_items", ["recipient_user_id"],
    )
    op.create_index(
        "ix_attention_items_organization_id",
        "attention_items", ["organization_id"],
    )
    op.create_index(
        "ix_attention_items_session_id",
        "attention_items", ["session_id"],
    )
    op.create_index(
        "ix_attention_items_created_at",
        "attention_items", ["created_at"],
    )
    op.create_index(
        "ix_attention_items_recipient_status",
        "attention_items", ["recipient_user_id", "status"],
    )
    op.create_index(
        "ix_attention_items_recipient_created",
        "attention_items", ["recipient_user_id", "created_at"],
    )
    op.create_index(
        "ix_attention_items_source",
        "attention_items", ["source_type", "source_id"],
    )
    op.create_index(
        "ix_attention_items_pending_unique",
        "attention_items",
        ["source_type", "source_id", "recipient_user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
        sqlite_where=sa.text("status = 'pending'"),
    )

    op.create_table(
        "erp_user_requests",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("created_by_user_id", sa.String(), nullable=True),
        sa.Column("request_type", sa.String(), nullable=False),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "status", sa.String(), nullable=False,
            server_default=sa.text("'open'"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by_user_id", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["session_id"], ["sessions.session_id"], ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["resolved_by_user_id"], ["users.id"], ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status IN ('open', 'resolved')",
            name="ck_erp_user_requests_status",
        ),
    )
    op.create_index(
        "ix_erp_user_requests_session_id",
        "erp_user_requests", ["session_id"],
    )
    op.create_index(
        "ix_erp_user_requests_created_by_user_id",
        "erp_user_requests", ["created_by_user_id"],
    )
    op.create_index(
        "ix_erp_user_requests_created_at",
        "erp_user_requests", ["created_at"],
    )
    op.create_index(
        "ix_erp_user_requests_session_status",
        "erp_user_requests", ["session_id", "status"],
    )
    op.create_index(
        "ix_erp_user_requests_creator",
        "erp_user_requests", ["created_by_user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_erp_user_requests_creator", table_name="erp_user_requests",
    )
    op.drop_index(
        "ix_erp_user_requests_session_status", table_name="erp_user_requests",
    )
    op.drop_index(
        "ix_erp_user_requests_created_at", table_name="erp_user_requests",
    )
    op.drop_index(
        "ix_erp_user_requests_created_by_user_id",
        table_name="erp_user_requests",
    )
    op.drop_index(
        "ix_erp_user_requests_session_id", table_name="erp_user_requests",
    )
    op.drop_table("erp_user_requests")

    op.drop_index(
        "ix_attention_items_pending_unique", table_name="attention_items",
    )
    op.drop_index(
        "ix_attention_items_source", table_name="attention_items",
    )
    op.drop_index(
        "ix_attention_items_recipient_created", table_name="attention_items",
    )
    op.drop_index(
        "ix_attention_items_recipient_status", table_name="attention_items",
    )
    op.drop_index(
        "ix_attention_items_created_at", table_name="attention_items",
    )
    op.drop_index(
        "ix_attention_items_session_id", table_name="attention_items",
    )
    op.drop_index(
        "ix_attention_items_organization_id", table_name="attention_items",
    )
    op.drop_index(
        "ix_attention_items_recipient_user_id", table_name="attention_items",
    )
    op.drop_table("attention_items")