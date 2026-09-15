"""allow account deletion with user foreign keys

Revision ID: 9ec08dd1761d
Revises: e4c60e2aa19e
Create Date: 2026-09-15 15:33:49.582308

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9ec08dd1761d'
down_revision: Union[str, Sequence[str], None] = 'e4c60e2aa19e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    user_set_null_fks = [
        ("sessions", "user_id", "users", "id"),
        ("feedback", "user_id", "users", "id"),
        ("project_documents", "user_id", "users", "id"),
        ("review_actions", "user_id", "users", "id"),
    ]

    for table, column, ref_table, ref_column in user_set_null_fks:
        constraint_name = f"{table}_{column}_fkey"

        with op.batch_alter_table(table) as batch_op:
            batch_op.alter_column(
                column,
                existing_type=sa.String(),
                nullable=True,
            )
            batch_op.drop_constraint(
                constraint_name,
                type_="foreignkey",
            )
            batch_op.create_foreign_key(
                constraint_name,
                ref_table,
                [column],
                [ref_column],
                ondelete="SET NULL",
            )


def downgrade() -> None:
    user_set_null_fks = [
        ("sessions", "user_id", "users", "id"),
        ("feedback", "user_id", "users", "id"),
        ("project_documents", "user_id", "users", "id"),
        ("review_actions", "user_id", "users", "id"),
    ]

    for table, column, ref_table, ref_column in user_set_null_fks:
        constraint_name = f"{table}_{column}_fkey"

        with op.batch_alter_table(table) as batch_op:
            batch_op.drop_constraint(
                constraint_name,
                type_="foreignkey",
            )
            batch_op.create_foreign_key(
                constraint_name,
                ref_table,
                [column],
                [ref_column],
            )
            batch_op.alter_column(
                column,
                existing_type=sa.String(),
                nullable=False,
            )
