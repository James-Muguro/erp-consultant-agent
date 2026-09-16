"""add versioning and proposed/actual stage to requirements and solution decisions

Revision ID: 8b69bcaa614c
Revises: a0df408841ef
Create Date: 2026-09-16 08:50:02.704403

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8b69bcaa614c'
down_revision: Union[str, Sequence[str], None] = 'a0df408841ef'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


"""
Existing rows become version 1, is_current=True (lineage_id = their own
id, since they're the first version of themselves). Solution decisions
default to stage='proposed', matching how they were created until now.
A partial unique index enforces "at most one current version per
lineage" at the database level, not just in application code.
"""

def upgrade() -> None:
    for table in ("requirement_items", "solution_decisions"):
        op.add_column(table, sa.Column("lineage_id", sa.String(), nullable=True))
        op.add_column(table, sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
        op.add_column(table, sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.true()))
        op.execute(f"UPDATE {table} SET lineage_id = id WHERE lineage_id IS NULL")
        op.alter_column(table, "lineage_id", nullable=False)

    op.add_column("solution_decisions", sa.Column("stage", sa.String(), nullable=False, server_default="proposed"))

    op.create_index(
        "ix_requirement_items_lineage_current", "requirement_items", ["lineage_id"],
        unique=True, postgresql_where=sa.text("is_current"), sqlite_where=sa.text("is_current"),
    )
    op.create_index(
        "ix_solution_decisions_lineage_current", "solution_decisions", ["lineage_id"],
        unique=True, postgresql_where=sa.text("is_current"), sqlite_where=sa.text("is_current"),
    )


def downgrade() -> None:
    op.drop_index("ix_solution_decisions_lineage_current", table_name="solution_decisions")
    op.drop_index("ix_requirement_items_lineage_current", table_name="requirement_items")
    op.drop_column("solution_decisions", "stage")
    for table in ("requirement_items", "solution_decisions"):
        op.drop_column(table, "is_current")
        op.drop_column(table, "version")
        op.drop_column(table, "lineage_id")