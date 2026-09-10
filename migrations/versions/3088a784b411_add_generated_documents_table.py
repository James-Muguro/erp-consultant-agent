"""add generated_documents table

Revision ID: 3088a784b411
Revises: 0ecbf2b6f9e6
Create Date: 2026-09-10 12:41:13.092615

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3088a784b411'
down_revision: Union[str, Sequence[str], None] = '0ecbf2b6f9e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'generated_documents',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('session_id', sa.String(), nullable=False),
        sa.Column('phase', sa.String(), nullable=False),
        sa.Column('label', sa.String(), nullable=False),
        sa.Column('filename', sa.String(), nullable=False),
        sa.Column('content_type', sa.String(), nullable=False),
        sa.Column('content', sa.LargeBinary(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['session_id'], ['sessions.session_id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_generated_documents_session_id'), 'generated_documents', ['session_id'])

def downgrade() -> None:
    op.drop_index(op.f('ix_generated_documents_session_id'), table_name='generated_documents')
    op.drop_table('generated_documents')
