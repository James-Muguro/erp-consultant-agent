"""add completion workflow columns to project_issues and test_case_records

Revision ID: e5a2b9c3d1f7
Revises: d4f1a8b2c9e3
Create Date: 2026-09-26 15:00:00.000000

Phase 2.5 Step 2 (D2). Adds the per-row state needed for the developer
completion / consultant confirm-reopen workflow. Both tables are
extended additively; existing rows receive safe defaults.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e5a2b9c3d1f7'
down_revision: Union[str, Sequence[str], None] = 'd4f1a8b2c9e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "project_issues",
        sa.Column(
            "completion_count", sa.Integer(), nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "project_issues",
        sa.Column("last_completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "project_issues",
        sa.Column("last_completed_by_user_id", sa.String(), nullable=True),
    )
    op.create_foreign_key(
        "fk_project_issues_last_completed_by_user_id",
        "project_issues", "users",
        ["last_completed_by_user_id"], ["id"],
        ondelete="SET NULL",
    )

    op.add_column(
        "test_case_records",
        sa.Column(
            "status", sa.String(), nullable=False,
            server_default=sa.text("'open'"),
        ),
    )
    op.add_column(
        "test_case_records",
        sa.Column(
            "completion_count", sa.Integer(), nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "test_case_records",
        sa.Column("last_completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "test_case_records",
        sa.Column("last_completed_by_user_id", sa.String(), nullable=True),
    )
    op.create_foreign_key(
        "fk_test_case_records_last_completed_by_user_id",
        "test_case_records", "users",
        ["last_completed_by_user_id"], ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_test_case_records_status",
        "test_case_records", ["status"],
    )


def downgrade() -> None:
    op.drop_index("ix_test_case_records_status", table_name="test_case_records")
    op.drop_constraint(
        "fk_test_case_records_last_completed_by_user_id",
        "test_case_records", type_="foreignkey",
    )
    op.drop_column("test_case_records", "last_completed_by_user_id")
    op.drop_column("test_case_records", "last_completed_at")
    op.drop_column("test_case_records", "completion_count")
    op.drop_column("test_case_records", "status")

    op.drop_constraint(
        "fk_project_issues_last_completed_by_user_id",
        "project_issues", type_="foreignkey",
    )
    op.drop_column("project_issues", "last_completed_by_user_id")
    op.drop_column("project_issues", "last_completed_at")
    op.drop_column("project_issues", "completion_count")