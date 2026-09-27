"""add session stakeholder submissions

Revision ID: 692e2495ae4e
Revises: a7f2b9e4c1d6
Create Date: 2026-09-26 12:20:25.730578

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '692e2495ae4e'
down_revision: Union[str, Sequence[str], None] = 'a7f2b9e4c1d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "session_stakeholder_submissions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("submitted_by_user_id", sa.String(), nullable=False),
        sa.Column("answers", sa.Text(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"], ["sessions.session_id"], ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["submitted_by_user_id"], ["users.id"], ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ssub_session_submitted_by",
        "session_stakeholder_submissions",
        ["session_id", "submitted_by_user_id"],
    )
    op.create_index(
        "ix_ssub_submitted_at",
        "session_stakeholder_submissions",
        ["submitted_at"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_ssub_submitted_at", table_name="session_stakeholder_submissions")
    op.drop_index("ix_ssub_session_submitted_by", table_name="session_stakeholder_submissions")
    op.drop_table("session_stakeholder_submissions")