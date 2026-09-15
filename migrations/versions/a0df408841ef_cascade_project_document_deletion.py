"""cascade project document deletion

Revision ID: a0df408841ef
Revises: 9ec08dd1761d
Create Date: 2026-09-15 15:38:16.240630

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a0df408841ef'
down_revision: Union[str, Sequence[str], None] = '9ec08dd1761d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("project_documents") as batch_op:
        batch_op.drop_constraint(
            "project_documents_session_id_fkey",
            type_="foreignkey",
        )
        batch_op.create_foreign_key(
            "project_documents_session_id_fkey",
            "sessions",
            ["session_id"],
            ["session_id"],
            ondelete="CASCADE",
        )


def downgrade() -> None:
    with op.batch_alter_table("project_documents") as batch_op:
        batch_op.drop_constraint(
            "project_documents_session_id_fkey",
            type_="foreignkey",
        )
        batch_op.create_foreign_key(
            "project_documents_session_id_fkey",
            "sessions",
            ["session_id"],
            ["session_id"],
        )
