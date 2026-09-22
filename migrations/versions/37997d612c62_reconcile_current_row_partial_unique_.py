"""reconcile current-row partial unique indexes on external_code

Revision ID: 37997d612c62
Revises: 7392e627e855
Create Date: 2026-09-22 07:48:17.069683

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '37997d612c62'
down_revision: Union[str, Sequence[str], None] = '7392e627e855'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


"""reconcile current-row partial unique indexes on external_code

Replaces the pre-existing full UNIQUE constraints on
(session_id, external_code) for requirement_items and process_steps,
which are incompatible with history-over-overwrite, with partial unique
indexes over the same columns restricted to is_current rows. Adds the
equivalent partial unique index for solution_decisions, which had no
prior full constraint.

Validates each entity's current-row uniqueness before creating its
index and raises a clear error on invalid legacy data. No data
corrections are performed. PostgreSQL is the production database.
"""

def _assert_no_duplicate_current_rows(table: str) -> None:
    op.execute(sa.text(f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM {table}
                WHERE is_current = TRUE
                GROUP BY session_id, external_code
                HAVING COUNT(*) > 1
            ) THEN
                RAISE EXCEPTION
                    'duplicate current rows on {table} block creation of '
                    'ix_{table}_session_external_code_current';
            END IF;
        END $$;
    """))


def upgrade() -> None:
    # 1. Drop the pre-existing full unique constraints that block
    #    historical rows from retaining their external_code.
    op.drop_constraint(
        "uq_requirement_session_external_code",
        "requirement_items",
        type_="unique",
    )
    op.drop_constraint(
        "uq_process_step_session_external_code",
        "process_steps",
        type_="unique",
    )

    # 2. Fail loudly if existing current rows already violate the
    #    invariant that each new partial unique index will enforce.
    _assert_no_duplicate_current_rows("requirement_items")
    _assert_no_duplicate_current_rows("process_steps")
    _assert_no_duplicate_current_rows("solution_decisions")

    # 3. Create the partial unique indexes that match the ORM model.
    op.create_index(
        "ix_requirement_items_session_external_code_current",
        "requirement_items",
        ["session_id", "external_code"],
        unique=True,
        postgresql_where=sa.text("is_current"),
    )
    op.create_index(
        "ix_process_steps_session_external_code_current",
        "process_steps",
        ["session_id", "external_code"],
        unique=True,
        postgresql_where=sa.text("is_current"),
    )
    op.create_index(
        "ix_solution_decisions_session_external_code_current",
        "solution_decisions",
        ["session_id", "external_code"],
        unique=True,
        postgresql_where=sa.text("is_current"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_solution_decisions_session_external_code_current",
        table_name="solution_decisions",
    )
    op.drop_index(
        "ix_process_steps_session_external_code_current",
        table_name="process_steps",
    )
    op.drop_index(
        "ix_requirement_items_session_external_code_current",
        table_name="requirement_items",
    )
    op.create_unique_constraint(
        "uq_requirement_session_external_code",
        "requirement_items",
        ["session_id", "external_code"],
    )
    op.create_unique_constraint(
        "uq_process_step_session_external_code",
        "process_steps",
        ["session_id", "external_code"],
    )