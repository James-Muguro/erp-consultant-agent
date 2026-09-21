"""add rationale to requirement items

Revision ID: 5ce7a828130c
Revises: aa9b0ebeb68c
Create Date: 2026-09-21 07:55:56.203853

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5ce7a828130c'
down_revision: Union[str, Sequence[str], None] = 'aa9b0ebeb68c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'requirement_items',
        sa.Column('rationale', sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('requirement_items', 'rationale')
