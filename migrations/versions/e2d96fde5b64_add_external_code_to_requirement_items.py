"""add external_code to requirement_items

Revision ID: e2d96fde5b64
Revises: d28bffc96920
Create Date: 2026-09-14 07:07:04.323523

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e2d96fde5b64'
down_revision: Union[str, Sequence[str], None] = 'd28bffc96920'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('requirement_items', sa.Column('external_code', sa.String(), nullable=True))
    op.create_index(op.f('ix_requirement_items_external_code'), 'requirement_items', ['external_code'])


def downgrade() -> None:
    op.drop_index(op.f('ix_requirement_items_external_code'), table_name='requirement_items')
    op.drop_column('requirement_items', 'external_code')
