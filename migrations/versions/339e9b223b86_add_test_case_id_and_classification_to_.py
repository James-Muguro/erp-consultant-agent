"""add test_case_id and classification to project_issues

Revision ID: 339e9b223b86
Revises: 598aff673b1b
Create Date: 2026-09-17 13:21:49.190394

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '339e9b223b86'
down_revision: Union[str, Sequence[str], None] = '598aff673b1b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("project_issues", sa.Column("test_case_id", sa.String(), nullable=True))
    op.add_column("project_issues", sa.Column("classification", sa.String(), nullable=True))
    op.create_index(op.f("ix_project_issues_test_case_id"), "project_issues", ["test_case_id"])
    op.create_foreign_key(
        "project_issues_test_case_id_fkey", "project_issues", "test_case_records",
        ["test_case_id"], ["id"], ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("project_issues_test_case_id_fkey", "project_issues", type_="foreignkey")
    op.drop_index(op.f("ix_project_issues_test_case_id"), table_name="project_issues")
    op.drop_column("project_issues", "classification")
    op.drop_column("project_issues", "test_case_id")
