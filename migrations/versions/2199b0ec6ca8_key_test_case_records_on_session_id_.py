"""key test_case_records on session_id, test_type, external_code

Revision ID: 2199b0ec6ca8
Revises: 37997d612c62
Create Date: 2026-09-22 12:07:04.965535

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2199b0ec6ca8'
down_revision: Union[str, Sequence[str], None] = '37997d612c62'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


"""
The canonical identity of a test case is (session_id, test_type,
external_code). `test_type` has always been a column on this table; it
was simply omitted from the constraint. This migration:

  1. Verifies that no existing (session_id, test_type, external_code)
     tuples collide. They cannot if the old constraint is intact — the
     old constraint (session_id, external_code) implies the new one —
     but the check is explicit so any surprise is a clear message rather
     than an opaque DDL error.
  2. Drops uq_test_case_session_external_code.
  3. Adds uq_test_case_session_type_external_code as
     UNIQUE (session_id, test_type, external_code).

"""

def _assert_no_duplicate_session_type_code() -> None:
    op.execute(sa.text("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM test_case_records
                GROUP BY session_id, test_type, external_code
                HAVING COUNT(*) > 1
            ) THEN
                RAISE EXCEPTION
                    'duplicate (session_id, test_type, external_code) rows '
                    'in test_case_records block creation of '
                    'uq_test_case_session_type_external_code';
            END IF;
        END $$;
    """))


def _assert_no_duplicate_session_code() -> None:
    op.execute(sa.text("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM test_case_records
                GROUP BY session_id, external_code
                HAVING COUNT(*) > 1
            ) THEN
                RAISE EXCEPTION
                    'cannot downgrade: two rows share (session_id, '
                    'external_code) but differ by test_type; resolve '
                    'manually before downgrading';
            END IF;
        END $$;
    """))


def upgrade() -> None:
    _assert_no_duplicate_session_type_code()
    op.drop_constraint(
        "uq_test_case_session_external_code",
        "test_case_records",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_test_case_session_type_external_code",
        "test_case_records",
        ["session_id", "test_type", "external_code"],
    )


def downgrade() -> None:
    _assert_no_duplicate_session_code()
    op.drop_constraint(
        "uq_test_case_session_type_external_code",
        "test_case_records",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_test_case_session_external_code",
        "test_case_records",
        ["session_id", "external_code"],
    )
