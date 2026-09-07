"""add is_casual to sessions

Revision ID: c0e480de24c2
Revises: 970b49d6d4d9
Create Date: 2026-09-07 11:46:19.575751

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c0e480de24c2'
down_revision: Union[str, Sequence[str], None] = '970b49d6d4d9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'sessions',
        sa.Column(
            'is_casual',
            sa.Boolean(),
            nullable=False,
            server_default='false',
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('sessions', 'is_casual')
