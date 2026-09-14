"""add test_case_records and training_step_records tables

Revision ID: 071a21e9b625
Revises: 4f5fa2e6e486
Create Date: 2026-09-14 12:17:55.615037

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '071a21e9b625'
down_revision: Union[str, Sequence[str], None] = '4f5fa2e6e486'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'test_case_records',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('session_id', sa.String(), nullable=False),
        sa.Column('test_type', sa.String(), nullable=False),
        sa.Column('external_code', sa.String(), nullable=True),
        sa.Column('scenario', sa.String(), nullable=False),
        sa.Column('priority', sa.String(), nullable=False),
        sa.Column('expected_result', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['session_id'], ['sessions.session_id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_test_case_records_session_id'), 'test_case_records', ['session_id'])

    op.create_table(
        'training_step_records',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('session_id', sa.String(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('instructions', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['session_id'], ['sessions.session_id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_training_step_records_session_id'), 'training_step_records', ['session_id'])


def downgrade() -> None:
    op.drop_index(op.f('ix_training_step_records_session_id'), table_name='training_step_records')
    op.drop_table('training_step_records')
    op.drop_index(op.f('ix_test_case_records_session_id'), table_name='test_case_records')
    op.drop_table('test_case_records')
