"""add versioning to process steps

Revision ID: 598aff673b1b
Revises: 8b69bcaa614c
Create Date: 2026-09-17 08:30:27.843641

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '598aff673b1b'
down_revision: Union[str, Sequence[str], None] = '8b69bcaa614c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


"""
Same pattern as requirement_items/solution_decisions: existing rows
become version 1, is_current=True, lineage_id = their own id.
"""


def upgrade() -> None:
    op.add_column("process_steps", sa.Column("lineage_id", sa.String(), nullable=True))
    op.add_column("process_steps", sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("process_steps", sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.execute("UPDATE process_steps SET lineage_id = id WHERE lineage_id IS NULL")
    op.alter_column("process_steps", "lineage_id", nullable=False)

    op.create_index(
        "ix_process_steps_lineage_current", "process_steps", ["lineage_id"],
        unique=True, postgresql_where=sa.text("is_current"), sqlite_where=sa.text("is_current"),
    )


def downgrade() -> None:
    op.drop_index("ix_process_steps_lineage_current", table_name="process_steps")
    op.drop_column("process_steps", "is_current")
    op.drop_column("process_steps", "version")
    op.drop_column("process_steps", "lineage_id")
