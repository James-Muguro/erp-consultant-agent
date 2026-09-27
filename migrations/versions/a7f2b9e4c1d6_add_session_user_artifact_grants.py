"""add session_user_artifact_grants table

Revision ID: a7f2b9e4c1d6
Revises: c4e8a1d7b2f9
Create Date: 2026-09-26 00:00:00.000000

Introduces the per-user, per-project, per-artifact access-grant model
that backs ERP User project-artifact access (Phase 2.3).

Semantics:
  * A grant is scoped to exactly one (session, user, artifact_type).
  * A grant does NOT establish project membership. Membership is
    derived from sessions.user_id (personal) or OrganizationMembership
    (organization-owned project); the grant table only answers "which
    artifacts may this already-a-member access?".
  * Revocation is soft (revoked_at / revoked_by_user_id), preserving the
    historical record. A partial unique index over
    (session_id, user_id, artifact_type) WHERE revoked_at IS NULL
    enforces at most one ACTIVE grant per identity while allowing any
    number of historical revoked rows.

Artifact types (application-enforced, not a Postgres ENUM so future
types do not require ALTER TYPE):
    requirements_questionnaire
    frd
    uat_scenarios
    training_materials

Designations:
    is_signatory        valid only when artifact_type = 'frd'
    is_uat_participant  valid only when artifact_type = 'uat_scenarios'
Both are enforced by CHECK constraints, portable across Postgres and
SQLite.

Non-destructive: no existing table, column, index, or constraint is
modified. Downgrade drops the table and its indexes cleanly; no data in
any other table is affected.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a7f2b9e4c1d6'
down_revision: Union[str, Sequence[str], None] = 'c4e8a1d7b2f9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "session_user_artifact_grants",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("artifact_type", sa.String(), nullable=False),
        sa.Column(
            "is_signatory",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "is_uat_participant",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("granted_by_user_id", sa.String(), nullable=True),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by_user_id", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["session_id"], ["sessions.session_id"], ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["granted_by_user_id"], ["users.id"], ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["revoked_by_user_id"], ["users.id"], ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "NOT is_signatory OR artifact_type = 'frd'",
            name="ck_session_user_artifact_grants_signatory_only_frd",
        ),
        sa.CheckConstraint(
            "NOT is_uat_participant OR artifact_type = 'uat_scenarios'",
            name="ck_session_user_artifact_grants_uat_only_uat",
        ),
    )

    op.create_index(
        "ix_session_user_artifact_grants_session_id",
        "session_user_artifact_grants", ["session_id"],
    )
    op.create_index(
        "ix_session_user_artifact_grants_user_id",
        "session_user_artifact_grants", ["user_id"],
    )
    # Partial unique index: at most one ACTIVE grant per identity.
    # Historical revoked rows (revoked_at IS NOT NULL) are exempt.
    op.create_index(
        "ix_session_user_artifact_grants_active_unique",
        "session_user_artifact_grants",
        ["session_id", "user_id", "artifact_type"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
        sqlite_where=sa.text("revoked_at IS NULL"),
    )
    op.create_index(
        "ix_session_user_artifact_grants_user_active",
        "session_user_artifact_grants",
        ["user_id", "revoked_at"],
    )
    op.create_index(
        "ix_session_user_artifact_grants_session_artifact",
        "session_user_artifact_grants",
        ["session_id", "artifact_type"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_session_user_artifact_grants_session_artifact",
        table_name="session_user_artifact_grants",
    )
    op.drop_index(
        "ix_session_user_artifact_grants_user_active",
        table_name="session_user_artifact_grants",
    )
    op.drop_index(
        "ix_session_user_artifact_grants_active_unique",
        table_name="session_user_artifact_grants",
    )
    op.drop_index(
        "ix_session_user_artifact_grants_user_id",
        table_name="session_user_artifact_grants",
    )
    op.drop_index(
        "ix_session_user_artifact_grants_session_id",
        table_name="session_user_artifact_grants",
    )
    op.drop_table("session_user_artifact_grants")