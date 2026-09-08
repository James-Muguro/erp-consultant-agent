"""add profile fields to users

Revision ID: 3a6e2d1c8f4b
Revises: 970b49d6d4d9
Create Date: 2026-09-08 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '3a6e2d1c8f4b'
down_revision: Union[str, Sequence[str], None] = '970b49d6d4d9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('name', sa.String(), nullable=True))
    op.add_column('users', sa.Column('profile_picture_url', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'profile_picture_url')
    op.drop_column('users', 'name')