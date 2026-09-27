"""add completion workflow columns to test_case_records

Revision ID: b7c4d2e9f8a5
Revises: f6b3c1d8e7a4
Create Date: 2026-09-27 10:00:00.000000

No-op.

An earlier migration on this chain, `e5a2b9c3d1f7` ("add completion
workflow columns to project_issues and test_case_records"), already
performs every column addition this revision originally intended. When
this migration was written, the two were not reconciled; running the
full chain from a fresh schema raises `DuplicateColumn` on
`test_case_records.status`.

Rather than delete the file (which would shift the head and require
every developer to re-point), the upgrade and downgrade are reduced to
no-ops. The chain is preserved; the schema effect is entirely carried
by e5a2b9c3d1f7.

If a future environment somehow needs the columns and e5a2b9c3d1f7
is not on the chain, fix that migration — do not un-no-op this one.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b7c4d2e9f8a5'
down_revision: Union[str, Sequence[str], None] = 'f6b3c1d8e7a4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Intentionally empty. See module docstring."""
    pass


def downgrade() -> None:
    """Intentionally empty. See module docstring."""
    pass