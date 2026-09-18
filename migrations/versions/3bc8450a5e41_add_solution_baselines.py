"""add solution baselines

Revision ID: 3bc8450a5e41
Revises: 339e9b223b86
Create Date: 2026-09-18 08:17:44.472209

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3bc8450a5e41'
down_revision: Union[str, Sequence[str], None] = '339e9b223b86'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "solution_baselines",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.session_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_solution_baselines_session_id"), "solution_baselines", ["session_id"])

    op.create_table(
        "solution_baseline_items",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("baseline_id", sa.String(), nullable=False),
        sa.Column("solution_decision_id", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["baseline_id"], ["solution_baselines.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["solution_decision_id"], ["solution_decisions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_solution_baseline_items_baseline_id"), "solution_baseline_items", ["baseline_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_solution_baseline_items_baseline_id"), table_name="solution_baseline_items")
    op.drop_table("solution_baseline_items")
    op.drop_index(op.f("ix_solution_baselines_session_id"), table_name="solution_baselines")
    op.drop_table("solution_baselines")