"""merge project intelligence migration heads

Revision ID: 4f5fa2e6e486
Revises: 536867117b89, e2d96fde5b64
Create Date: 2026-09-14 07:48:05.027335

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4f5fa2e6e486'
down_revision: Union[str, Sequence[str], None] = ('536867117b89', 'e2d96fde5b64')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
