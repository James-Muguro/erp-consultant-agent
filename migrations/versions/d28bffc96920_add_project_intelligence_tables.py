"""add project intelligence tables

Revision ID: d28bffc96920
Revises: 3088a784b411
Create Date: 2026-09-10 17:33:52.321063

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd28bffc96920'
down_revision: Union[str, Sequence[str], None] = '3088a784b411'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "requirement_items",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("priority", sa.String(), nullable=False),
        sa.Column("req_type", sa.String(), nullable=False),
        sa.Column("acceptance_criteria", sa.Text(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("source_excerpt", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.session_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_requirement_items_session_id",
        "requirement_items",
        ["session_id"],
        unique=False,
    )

    op.create_table(
        "process_steps",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("process_name", sa.String(), nullable=False),
        sa.Column("step_number", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("responsible_role", sa.String(), nullable=True),
        sa.Column("requirement_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.session_id"]),
        sa.ForeignKeyConstraint(["requirement_id"], ["requirement_items.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_process_steps_session_id",
        "process_steps",
        ["session_id"],
        unique=False,
    )

    op.create_table(
        "solution_decisions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("decision_type", sa.String(), nullable=False),
        sa.Column("component", sa.String(), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("requirement_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.session_id"]),
        sa.ForeignKeyConstraint(["requirement_id"], ["requirement_items.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_solution_decisions_session_id",
        "solution_decisions",
        ["session_id"],
        unique=False,
    )

    op.create_table(
        "project_issues",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("issue_type", sa.String(), nullable=False),
        sa.Column("severity", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("related_object_type", sa.String(), nullable=True),
        sa.Column("related_object_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.session_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_project_issues_session_id",
        "project_issues",
        ["session_id"],
        unique=False,
    )

    op.create_table(
        "review_actions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("object_type", sa.String(), nullable=False),
        sa.Column("object_id", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.session_id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_review_actions_session_id",
        "review_actions",
        ["session_id"],
        unique=False,
    )

    op.create_table(
        "trace_links",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("source_type", sa.String(), nullable=False),
        sa.Column("source_id", sa.String(), nullable=False),
        sa.Column("target_type", sa.String(), nullable=False),
        sa.Column("target_id", sa.String(), nullable=False),
        sa.Column("relationship", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.session_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_trace_links_session_id",
        "trace_links",
        ["session_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_trace_links_session_id", table_name="trace_links")
    op.drop_table("trace_links")

    op.drop_index("ix_review_actions_session_id", table_name="review_actions")
    op.drop_table("review_actions")

    op.drop_index("ix_project_issues_session_id", table_name="project_issues")
    op.drop_table("project_issues")

    op.drop_index(
        "ix_solution_decisions_session_id",
        table_name="solution_decisions",
    )
    op.drop_table("solution_decisions")

    op.drop_index("ix_process_steps_session_id", table_name="process_steps")
    op.drop_table("process_steps")

    op.drop_index(
        "ix_requirement_items_session_id",
        table_name="requirement_items",
    )
    op.drop_table("requirement_items")
