"""add ON DELETE CASCADE to session-scoped foreign keys

Revision ID: e4c60e2aa19e
Revises: 071a21e9b625
Create Date: 2026-09-15 13:08:37.924616

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e4c60e2aa19e'
down_revision: Union[str, Sequence[str], None] = '071a21e9b625'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


"""
Fixes a live bug: deleting a session (via permanent delete or account
deletion) currently raises ForeignKeyViolation on any project with
requirements/process-steps/etc, since those tables' FKs default to
RESTRICT. Constraint names below assume Postgres's default auto-naming
(<table>_<column>_fkey) since none were given an explicit name at
creation - verify with \\d <table> in psql if a drop fails.
"""

# (table, column, ref_table, ref_column, ondelete)
CASCADE_FKS = [
    ("feedback", "session_id", "sessions", "session_id", "CASCADE"),
    ("generated_documents", "session_id", "sessions", "session_id", "CASCADE"),
    ("requirement_items", "session_id", "sessions", "session_id", "CASCADE"),
    ("process_steps", "session_id", "sessions", "session_id", "CASCADE"),
    ("process_steps", "requirement_id", "requirement_items", "id", "SET NULL"),
    ("solution_decisions", "session_id", "sessions", "session_id", "CASCADE"),
    ("solution_decisions", "requirement_id", "requirement_items", "id", "SET NULL"),
    ("test_case_records", "session_id", "sessions", "session_id", "CASCADE"),
    ("training_step_records", "session_id", "sessions", "session_id", "CASCADE"),
    ("project_issues", "session_id", "sessions", "session_id", "CASCADE"),
    ("review_actions", "session_id", "sessions", "session_id", "CASCADE"),
    ("trace_links", "session_id", "sessions", "session_id", "CASCADE"),
]


def upgrade() -> None:
    for table, column, ref_table, ref_column, ondelete in CASCADE_FKS:
        constraint_name = f"{table}_{column}_fkey"
        op.drop_constraint(constraint_name, table, type_="foreignkey")
        op.create_foreign_key(constraint_name, table, ref_table, [column], [ref_column], ondelete=ondelete)


def downgrade() -> None:
    for table, column, ref_table, ref_column, _ in CASCADE_FKS:
        constraint_name = f"{table}_{column}_fkey"
        op.drop_constraint(constraint_name, table, type_="foreignkey")
        op.create_foreign_key(constraint_name, table, ref_table, [column], [ref_column])