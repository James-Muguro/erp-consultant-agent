"""add organizations, organization_memberships, user_roles; add
sessions.organization_id; backfill FUNCTIONAL_CONSULTANT for existing users

Revision ID: f3a8c1b5e9d2
Revises: 2199b0ec6ca8
Create Date: 2026-09-24 00:00:00.000000

This migration introduces the RBAC and multi-tenancy foundation:

  1. organizations            - tenant context
  2. organization_memberships - many-to-many user<->organization with role
  3. user_roles               - application role grants
  4. sessions.organization_id - nullable FK; NULL = personal project,
                                non-NULL = organization-owned project

Non-destructive: no existing table, column, index, or constraint is
modified. sessions.organization_id is added nullable so every existing
session row remains valid and stays a personal project.

Backfill: every existing user receives FUNCTIONAL_CONSULTANT, the only
single application role whose permission set preserves the current
effective access of all users (full read/write on their own projects).
The backfill is guarded by WHERE NOT EXISTS so it is idempotent if
reapplied to a partially-migrated database; in normal operation the
guard is a no-op because user_roles is created by this migration.

Downgrade drops the three new tables and the new column. The three
tables have no dependents outside this migration (nothing in this
schema yet references them), so the reverse is a clean removal. All
existing user, session, and project data is preserved byte-for-byte
by both directions.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f3a8c1b5e9d2'
down_revision: Union[str, Sequence[str], None] = '2199b0ec6ca8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. organizations
    # ------------------------------------------------------------------
    op.create_table(
        "organizations",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_organizations_created_by", "organizations", ["created_by"],
    )

    # ------------------------------------------------------------------
    # 2. organization_memberships
    # ------------------------------------------------------------------
    op.create_table(
        "organization_memberships",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("organization_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id", "user_id",
            name="uq_organization_membership_org_user",
        ),
    )
    op.create_index(
        "ix_organization_memberships_organization_id",
        "organization_memberships", ["organization_id"],
    )
    op.create_index(
        "ix_organization_memberships_user_id",
        "organization_memberships", ["user_id"],
    )

    # ------------------------------------------------------------------
    # 3. user_roles
    # ------------------------------------------------------------------
    op.create_table(
        "user_roles",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "role", name="uq_user_role_user_role",
        ),
    )
    op.create_index(
        "ix_user_roles_user_id", "user_roles", ["user_id"],
    )

    # ------------------------------------------------------------------
    # 4. sessions.organization_id
    # ------------------------------------------------------------------
    op.add_column(
        "sessions",
        sa.Column("organization_id", sa.String(), nullable=True),
    )
    op.create_foreign_key(
        "sessions_organization_id_fkey",
        "sessions", "organizations",
        ["organization_id"], ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_sessions_organization_id", "sessions", ["organization_id"],
    )

    # ------------------------------------------------------------------
    # 5. Backfill: every existing user gets FUNCTIONAL_CONSULTANT
    # ------------------------------------------------------------------
    # Rationale: before this migration, all users had identical effective
    # access - full read/write on their own projects. Functional
    # Consultant is the only single application role whose permission
    # set preserves that capability. Granting additional roles would
    # expand access; granting a narrower role would reduce it.
    #
    # The id is generated per-row via md5(random() || clock_timestamp()),
    # which produces a 32-character lowercase hex string matching the
    # application's existing id convention (uuid4().hex). The WHERE NOT
    # EXISTS guard makes the statement idempotent; in normal operation
    # user_roles was just created empty by this migration, so it inserts
    # exactly one row per existing user.
    op.execute(sa.text("""
        INSERT INTO user_roles (id, user_id, role, created_at)
        SELECT
            md5(random()::text || clock_timestamp()::text || u.id),
            u.id,
            'functional_consultant',
            now()
        FROM users u
        WHERE NOT EXISTS (
            SELECT 1 FROM user_roles ur
            WHERE ur.user_id = u.id
              AND ur.role = 'functional_consultant'
        )
    """))


def downgrade() -> None:
    # The backfilled user_roles rows cannot be distinguished from later
    # organic grants, so the reverse of this migration drops the entire
    # user_roles table along with the other two new tables and the new
    # sessions column. This is honest: upgrade is purely additive;
    # downgrade removes the RBAC/multitenancy data model introduced by
    # this migration.
    op.drop_index("ix_sessions_organization_id", table_name="sessions")
    op.drop_constraint(
        "sessions_organization_id_fkey", "sessions", type_="foreignkey",
    )
    op.drop_column("sessions", "organization_id")

    op.drop_index("ix_user_roles_user_id", table_name="user_roles")
    op.drop_table("user_roles")

    op.drop_index(
        "ix_organization_memberships_user_id",
        table_name="organization_memberships",
    )
    op.drop_index(
        "ix_organization_memberships_organization_id",
        table_name="organization_memberships",
    )
    op.drop_table("organization_memberships")

    op.drop_index("ix_organizations_created_by", table_name="organizations")
    op.drop_table("organizations")