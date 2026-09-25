"""add auth tokens, MFA records, audit events; add auth state columns to users

Revision ID: c4e8a1d7b2f9
Revises: f3a8c1b5e9d2
Create Date: 2026-09-25 00:00:00.000000

Introduces the persistent structures required by the Phase 1 auth build:

  1. users.email_verified_at       - NULL until email verification completes
  2. users.failed_login_count      - consecutive failed password attempts
  3. users.locked_until            - account-level lock expiry (progressive
                                     login protection)
  4. users.last_login_at           - timestamp of last successful login
  5. auth_refresh_tokens           - revocable, rotated refresh-token records
  6. auth_password_reset_tokens    - single-use password-reset tokens
  7. auth_email_verification_tokens - single-use email-verification tokens
  8. auth_otp_records              - email OTP MFA (hashed codes)
  9. auth_audit_events             - auth audit log (no secrets)

Non-destructive: no existing table, column, index, or constraint is
modified. Every new column on `users` is either nullable or NOT NULL with
a server default, so the ALTERs succeed against populated tables.

Backfill: existing users are marked as email-verified by setting
`email_verified_at = created_at`. Rationale: those accounts were created
before the verification flow existed and must remain able to log in;
leaving them NULL would either lock them out or require the login flow to
special-case "account predates migration X" forever. The UPDATE is
guarded by `WHERE email_verified_at IS NULL` so it is idempotent if
reapplied.

Downgrade drops the four users columns and the five new tables. All
existing data in other tables is preserved byte-for-byte.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c4e8a1d7b2f9'
down_revision: Union[str, Sequence[str], None] = 'f3a8c1b5e9d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. users - auth state columns
    # ------------------------------------------------------------------
    # email_verified_at is nullable: NULL means "never verified".
    op.add_column(
        "users",
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    # failed_login_count is NOT NULL with a server default so the ALTER
    # succeeds against populated tables. The default is also useful for
    # direct DB inserts outside the ORM.
    op.add_column(
        "users",
        sa.Column(
            "failed_login_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "users",
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ------------------------------------------------------------------
    # 2. auth_refresh_tokens
    # ------------------------------------------------------------------
    op.create_table(
        "auth_refresh_tokens",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("family_id", sa.String(), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_reason", sa.String(), nullable=True),
        sa.Column("user_agent", sa.String(), nullable=True),
        sa.Column("ip_address", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "token_hash", name="uq_auth_refresh_tokens_token_hash",
        ),
    )
    op.create_index(
        "ix_auth_refresh_tokens_user_id",
        "auth_refresh_tokens", ["user_id"],
    )
    op.create_index(
        "ix_auth_refresh_tokens_family_id",
        "auth_refresh_tokens", ["family_id"],
    )
    op.create_index(
        "ix_auth_refresh_tokens_token_hash",
        "auth_refresh_tokens", ["token_hash"],
    )
    op.create_index(
        "ix_auth_refresh_tokens_expires_at",
        "auth_refresh_tokens", ["expires_at"],
    )
    op.create_index(
        "ix_auth_refresh_tokens_revoked_at",
        "auth_refresh_tokens", ["revoked_at"],
    )
    op.create_index(
        "ix_auth_refresh_tokens_user_revoked",
        "auth_refresh_tokens", ["user_id", "revoked_at"],
    )

    # ------------------------------------------------------------------
    # 3. auth_password_reset_tokens
    # ------------------------------------------------------------------
    op.create_table(
        "auth_password_reset_tokens",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "token_hash", name="uq_auth_password_reset_tokens_token_hash",
        ),
    )
    op.create_index(
        "ix_auth_password_reset_tokens_user_id",
        "auth_password_reset_tokens", ["user_id"],
    )
    op.create_index(
        "ix_auth_password_reset_tokens_token_hash",
        "auth_password_reset_tokens", ["token_hash"],
    )
    op.create_index(
        "ix_auth_password_reset_tokens_expires_at",
        "auth_password_reset_tokens", ["expires_at"],
    )

    # ------------------------------------------------------------------
    # 4. auth_email_verification_tokens
    # ------------------------------------------------------------------
    op.create_table(
        "auth_email_verification_tokens",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "token_hash", name="uq_auth_email_verification_tokens_token_hash",
        ),
    )
    op.create_index(
        "ix_auth_email_verification_tokens_user_id",
        "auth_email_verification_tokens", ["user_id"],
    )
    op.create_index(
        "ix_auth_email_verification_tokens_token_hash",
        "auth_email_verification_tokens", ["token_hash"],
    )
    op.create_index(
        "ix_auth_email_verification_tokens_expires_at",
        "auth_email_verification_tokens", ["expires_at"],
    )

    # ------------------------------------------------------------------
    # 5. auth_otp_records
    # ------------------------------------------------------------------
    op.create_table(
        "auth_otp_records",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("purpose", sa.String(), nullable=False),
        sa.Column("code_hash", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip_address", sa.String(), nullable=True),
        sa.Column("user_agent", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_auth_otp_records_user_id",
        "auth_otp_records", ["user_id"],
    )
    op.create_index(
        "ix_auth_otp_records_purpose",
        "auth_otp_records", ["purpose"],
    )
    op.create_index(
        "ix_auth_otp_records_expires_at",
        "auth_otp_records", ["expires_at"],
    )
    op.create_index(
        "ix_auth_otp_records_user_purpose",
        "auth_otp_records", ["user_id", "purpose"],
    )

    # ------------------------------------------------------------------
    # 6. auth_audit_events
    # ------------------------------------------------------------------
    op.create_table(
        "auth_audit_events",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=True),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("outcome", sa.String(), nullable=False),
        sa.Column("ip_address", sa.String(), nullable=True),
        sa.Column("user_agent", sa.String(), nullable=True),
        sa.Column("event_metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_auth_audit_events_user_id",
        "auth_audit_events", ["user_id"],
    )
    op.create_index(
        "ix_auth_audit_events_event_type",
        "auth_audit_events", ["event_type"],
    )
    op.create_index(
        "ix_auth_audit_events_created_at",
        "auth_audit_events", ["created_at"],
    )
    op.create_index(
        "ix_auth_audit_events_user_created",
        "auth_audit_events", ["user_id", "created_at"],
    )
    op.create_index(
        "ix_auth_audit_events_type_created",
        "auth_audit_events", ["event_type", "created_at"],
    )

    # ------------------------------------------------------------------
    # 7. Backfill: existing users are marked email-verified
    # ------------------------------------------------------------------
    # Accounts created before this migration never had a verification
    # flow. Treating them as verified (via created_at as the verification
    # timestamp) keeps them able to authenticate. The WHERE clause makes
    # the statement idempotent.
    op.execute(sa.text(
        "UPDATE users "
        "SET email_verified_at = created_at "
        "WHERE email_verified_at IS NULL"
    ))


def downgrade() -> None:
    # Drop child tables first (all have CASCADE-to-users FKs, so order
    # between them does not matter, but explicit reverse-of-upgrade order
    # keeps the diff readable).
    op.drop_index(
        "ix_auth_audit_events_type_created",
        table_name="auth_audit_events",
    )
    op.drop_index(
        "ix_auth_audit_events_user_created",
        table_name="auth_audit_events",
    )
    op.drop_index(
        "ix_auth_audit_events_created_at",
        table_name="auth_audit_events",
    )
    op.drop_index(
        "ix_auth_audit_events_event_type",
        table_name="auth_audit_events",
    )
    op.drop_index(
        "ix_auth_audit_events_user_id",
        table_name="auth_audit_events",
    )
    op.drop_table("auth_audit_events")

    op.drop_index(
        "ix_auth_otp_records_user_purpose",
        table_name="auth_otp_records",
    )
    op.drop_index(
        "ix_auth_otp_records_expires_at",
        table_name="auth_otp_records",
    )
    op.drop_index(
        "ix_auth_otp_records_purpose",
        table_name="auth_otp_records",
    )
    op.drop_index(
        "ix_auth_otp_records_user_id",
        table_name="auth_otp_records",
    )
    op.drop_table("auth_otp_records")

    op.drop_index(
        "ix_auth_email_verification_tokens_expires_at",
        table_name="auth_email_verification_tokens",
    )
    op.drop_index(
        "ix_auth_email_verification_tokens_token_hash",
        table_name="auth_email_verification_tokens",
    )
    op.drop_index(
        "ix_auth_email_verification_tokens_user_id",
        table_name="auth_email_verification_tokens",
    )
    op.drop_table("auth_email_verification_tokens")

    op.drop_index(
        "ix_auth_password_reset_tokens_expires_at",
        table_name="auth_password_reset_tokens",
    )
    op.drop_index(
        "ix_auth_password_reset_tokens_token_hash",
        table_name="auth_password_reset_tokens",
    )
    op.drop_index(
        "ix_auth_password_reset_tokens_user_id",
        table_name="auth_password_reset_tokens",
    )
    op.drop_table("auth_password_reset_tokens")

    op.drop_index(
        "ix_auth_refresh_tokens_user_revoked",
        table_name="auth_refresh_tokens",
    )
    op.drop_index(
        "ix_auth_refresh_tokens_revoked_at",
        table_name="auth_refresh_tokens",
    )
    op.drop_index(
        "ix_auth_refresh_tokens_expires_at",
        table_name="auth_refresh_tokens",
    )
    op.drop_index(
        "ix_auth_refresh_tokens_token_hash",
        table_name="auth_refresh_tokens",
    )
    op.drop_index(
        "ix_auth_refresh_tokens_family_id",
        table_name="auth_refresh_tokens",
    )
    op.drop_index(
        "ix_auth_refresh_tokens_user_id",
        table_name="auth_refresh_tokens",
    )
    op.drop_table("auth_refresh_tokens")

    # ------------------------------------------------------------------
    # users columns (last: nothing else depends on them)
    # ------------------------------------------------------------------
    op.drop_column("users", "last_login_at")
    op.drop_column("users", "locked_until")
    op.drop_column("users", "failed_login_count")
    op.drop_column("users", "email_verified_at")