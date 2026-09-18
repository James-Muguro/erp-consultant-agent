"""add needs_retest to test_case_records

Revision ID: aa9b0ebeb68c
Revises: 3bc8450a5e41
Create Date: 2026-09-18 13:25:58.538707

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'aa9b0ebeb68c'
down_revision: Union[str, Sequence[str], None] = '3bc8450a5e41'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("test_case_records", sa.Column("needs_retest", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("test_case_records", "needs_retest")
