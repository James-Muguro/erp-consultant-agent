"""
ORM models for the persistence layer.

SessionRecord stores each project session as a JSON blob (`data`) alongside
a handful of indexed columns pulled out for querying - this mirrors the
existing SessionState.to_dict()/from_dict() shape exactly, so the migration
from file-based JSON to a database is a storage-location change, not a
schema redesign. A full relational schema (normalized conversation turns,
phase outputs, etc.) is worth doing once the UI/API need to query into
those pieces directly - not needed yet.

Identity, roles, and multi-tenancy:

  * User is the application identity.
  * UserRoleRecord grants application roles (erp_user,
    functional_consultant, developer, marketer). Users may hold multiple
    roles simultaneously; effective permissions are the union of the
    permission sets of every role held. There is no combined-role
    concept and no single 'role' column on users.
  * Organization is a tenant context. It is NOT an application role.
  * OrganizationMembership is a many-to-many join between users and
    organizations, carrying the member's organization role
    (owner/admin/member). Organization roles are a separate axis from
    application roles and grant no feature permissions.
  * SessionRecord.organization_id is NULL for personal projects and
    non-NULL for organization-owned projects. Personal project access
    still uses sessions.user_id == current_user.id; organization project
    access requires an active OrganizationMembership for the owning
    organization.
  * Organization deletion is RESTRICTed while projects exist
    (organization_id uses ON DELETE RESTRICT), so an ordinary
    organization delete cannot silently destroy project history.

Authentication persistence (added by the auth build):

  * User gains email verification state and progressive-login state.
  * AuthRefreshToken stores hashed, revocable refresh tokens with
    rotation-family identity for reuse detection.
  * AuthPasswordResetToken and AuthEmailVerificationToken store hashed,
    single-use tokens with expiry.
  * AuthOtpRecord stores hashed OTP codes for email MFA.
  * AuthAuditEvent is the auth audit log; it never contains secrets.

Session ownership and deletion semantics: every table whose rows have no
lifecycle independent of the owning session declares
ON DELETE CASCADE on its sessions.session_id foreign key. This is the
schema-level guarantee that deleting a session does not fail with a
ForeignKeyViolation because a child row still references it, and it means
application code does not have to know every child table by name. Tables
whose rows have independent lifecycle (users, feedback rows retained for
analytics/user attribution) preserve their current behavior.
"""
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON

from src.db.base import Base, engine


def _json_type():
    """Use native JSONB on Postgres, a portable JSON column everywhere else
    (SQLite/others) - avoids importing a Postgres-only type on a SQLite
    engine."""
    if engine.dialect.name == "postgresql":
        return JSONB
    return JSON


def _utcnow():
    return datetime.now(timezone.utc)


# ============================================================================
# Sessions and identity
# ============================================================================
class SessionRecord(Base):
    __tablename__ = "sessions"

    session_id = Column(String, primary_key=True)
    user_id = Column(
        String,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    # NULL = personal project (owned by sessions.user_id under the
    # existing personal-access rule). Non-NULL = organization-owned
    # project, in which case access is determined by an active
    # OrganizationMembership for this organization, not by sessions.user_id.
    # RESTRICT on delete: an organization cannot be removed while it still
    # owns projects, preventing silent data loss.
    organization_id = Column(
        String,
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=True, index=True,
    )
    project_name = Column(String, index=True, nullable=False)
    module = Column(String, nullable=False)
    erp_system = Column(String, nullable=False)
    current_phase = Column(String, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(
        DateTime(timezone=True), nullable=False, default=_utcnow,
        onupdate=_utcnow, index=True,
    )
    archived_at = Column(DateTime(timezone=True), nullable=True, index=True)
    is_casual = Column(
        Boolean, nullable=False, default=False,
        server_default=text("false"),
    )
    data = Column(_json_type()(), nullable=False)


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True)
    email = Column(String, unique=True, nullable=False, index=True)
    name = Column(String, nullable=True)
    profile_picture_url = Column(Text, nullable=True)
    hashed_password = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)

    # ------------------------------------------------------------------
    # Authentication state (added by the auth build)
    # ------------------------------------------------------------------
    # email_verified_at: NULL = never verified; non-NULL = the UTC
    # timestamp at which the user completed email verification. The
    # login flow consults this for any feature that requires a verified
    # address. Pre-existing accounts were backfilled to created_at by
    # the migration that introduced this column, because they were
    # created before the verification flow existed and must remain
    # able to log in.
    email_verified_at = Column(
        DateTime(timezone=True), nullable=True,
    )
    # failed_login_count: number of consecutive failed password attempts
    # since the last successful login (or since the last counter reset).
    # Used together with locked_until for progressive abuse protection.
    # Reset to 0 on successful authentication.
    failed_login_count = Column(
        Integer, nullable=False, default=0, server_default=text("0"),
    )
    # locked_until: when non-NULL and in the future, the account is
    # locked and password authentication must be refused until this
    # timestamp. Lockout is time-bounded on purpose so an attacker
    # cannot permanently disable an account by triggering the counter;
    # rate limiting on the endpoint is the primary control and this is
    # the account-level backstop.
    locked_until = Column(
        DateTime(timezone=True), nullable=True,
    )
    # last_login_at: timestamp of the most recent successful
    # authentication. Informational; used for the /me response and for
    # security investigation. Never used as an authorization input.
    last_login_at = Column(
        DateTime(timezone=True), nullable=True,
    )


# ============================================================================
# Organizations and RBAC
# ============================================================================
class Organization(Base):
    """Tenant context. Created by an 'organization' signup, at which point
    the creating user becomes an OrganizationMembership with role='owner'.

    Deliberately minimal at this stage: id, name, creator attribution,
    timestamp. Fields for capabilities that do not yet have a design
    (billing, project-visibility policy, subscription state, firm
    knowledge base) are NOT invented here - each will arrive via its own
    migration when the capability is actually built.

    created_by is nullable with SET NULL, matching the attribution pattern
    on sessions.user_id and review_actions.user_id. If the creating user
    is deleted, the organization itself is preserved; ownership of the
    organization flows through OrganizationMembership, not through
    created_by.
    """
    __tablename__ = "organizations"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    created_by = Column(
        String,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)


class OrganizationMembership(Base):
    """Many-to-many join between users and organizations, carrying the
    member's organization role.

    The role column here is an ORGANIZATION role (owner/admin/member),
    not an application role. Application roles live on UserRoleRecord.
    The two axes are independent: organization roles grant administrative
    capability inside one organization and no feature permissions
    anywhere; application roles grant feature permissions and no
    organization administrative capability.

    Uniqueness on (organization_id, user_id) prevents a user from holding
    two membership rows in the same organization. A user can be a member
    of many organizations simultaneously via many rows here.

    v1 has no soft-delete / 'inactive' state. A membership exists or it
    does not; leaving an organization deletes the row. If a pending or
    suspended state is introduced later, it becomes a column here and a
    filter in the RBAC lookup.
    """
    __tablename__ = "organization_memberships"

    id = Column(String, primary_key=True)
    organization_id = Column(
        String,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    user_id = Column(
        String,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    role = Column(String, nullable=False)  # 'owner' | 'admin' | 'member'
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (
        UniqueConstraint(
            "organization_id", "user_id",
            name="uq_organization_membership_org_user",
        ),
    )


class UserRoleRecord(Base):
    """Application role grant. One row per (user, role) pair.

    Multiple rows per user are the norm: a user may hold Functional
    Consultant and Developer simultaneously, in which case their
    effective permissions are the union of the two role permission sets.
    There is no combined-role concept (no 'functional_developer') and no
    single 'role' column on users.

    Named UserRoleRecord (not UserRole) to avoid a collision with the
    UserRole application-role enum in src/auth/permissions.py, matching
    the existing convention (TestCaseRecord, TrainingStepRecord, ...).

    Unique on (user_id, role) prevents duplicate grants of the same role
    to the same user. CASCADE on user_id: deleting a user removes their
    role grants, which is the intended lifecycle.
    """
    __tablename__ = "user_roles"

    id = Column(String, primary_key=True)
    user_id = Column(
        String,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    role = Column(String, nullable=False)  # 'erp_user' | 'functional_consultant' | 'developer' | 'marketer'
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (
        UniqueConstraint("user_id", "role", name="uq_user_role_user_role"),
    )


# ============================================================================
# Authentication: tokens, MFA, audit
# ============================================================================
# Raw token material (refresh tokens, password-reset tokens, email-
# verification tokens, OTP codes) is NEVER stored in plaintext. Every
# table in this section stores a SHA-256 hex digest of the token under
# a `*_hash` column. SHA-256 is used rather than bcrypt because the
# underlying secrets are cryptographically random (or, for OTPs, short
# but protected by attempt limits + short expiry), so the deliberate
# slowness of password hashing is not needed here and would add latency
# to every refresh / verification.
#
# Every table also declares a `user_id` FK with ON DELETE CASCADE, so
# deleting a user removes all of their auth state in the same
# transaction. The audit log is the exception: its user_id uses
# ON DELETE SET NULL, so the historical record of auth events survives
# account deletion for security investigation.


class AuthRefreshToken(Base):
    """Server-side refresh-token / session record.

    Access tokens are short-lived JWTs; refresh tokens are long-lived
    opaque random strings whose SHA-256 digest is stored here. The raw
    refresh token is returned to the client once, at issuance, and is
    never retrievable from the database.

    Rotation. Every successful use of a refresh token issues a new
    refresh token and revokes the current one (revoked_at set,
    revoked_reason='rotated'). Reuse detection: if a token that was
    already rotated is presented again, that is treated as a token-theft
    signal; the entire family (family_id) is revoked, and a
    RefreshTokenReuseDetected event is written to the audit log.

    Family identity. All tokens issued from a single login share the same
    family_id. Rotation preserves the family; reuse revokes it. A fresh
    login always starts a new family.

    Revocation reasons used by the service layer (documented so callers
    write consistent values):

        'rotated'          superseded by the next token in the family
        'logout'           user explicitly logged this session out
        'logout_all'       user signed out of all devices
        'reuse_detected'   token presented after it was already rotated
                           (whole family revoked)
        'password_reset'   password reset completed; sessions invalidated
        'password_change'  password changed by authenticated user
        'admin_revoke'     reserved for a future administrative action

    No raw refresh token is stored here or logged anywhere.
    """
    __tablename__ = "auth_refresh_tokens"

    id = Column(String, primary_key=True)
    user_id = Column(
        String,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # All tokens from a single login share this identifier. Rotation
    # preserves it; reuse detection revokes every row with the same value.
    family_id = Column(String, nullable=False, index=True)
    # SHA-256 hex digest of the raw refresh token. Unique so lookup is a
    # single indexed probe and two live tokens cannot collide.
    token_hash = Column(String, nullable=False, unique=True, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True, index=True)
    # Free-text reason; see class docstring for the expected values.
    revoked_reason = Column(String, nullable=True)
    # Metadata captured at issuance for security investigation. Neither
    # field is used for authorization decisions.
    user_agent = Column(String, nullable=True)
    ip_address = Column(String, nullable=True)

    __table_args__ = (
        # "All active sessions for a user" (logout-all-devices).
        Index(
            "ix_auth_refresh_tokens_user_revoked",
            "user_id", "revoked_at",
        ),
    )


class AuthPasswordResetToken(Base):
    """Password-reset token record.

    The raw token is emailed to the user; only its SHA-256 digest is
    stored here. Tokens are short-lived and single-use: a successful
    reset sets used_at, and any subsequent presentation of the same
    token is rejected. Request-time behavior (returning the same
    externally-visible response whether or not the email corresponds
    to an account) is the service layer's concern; this table only
    stores tokens that were actually issued.
    """
    __tablename__ = "auth_password_reset_tokens"

    id = Column(String, primary_key=True)
    user_id = Column(
        String,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    token_hash = Column(String, nullable=False, unique=True, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    used_at = Column(DateTime(timezone=True), nullable=True)


class AuthEmailVerificationToken(Base):
    """Email-verification token record.

    Issued at signup and on resend. The raw token is emailed to the user;
    only its SHA-256 digest is stored here. Tokens are short-lived and
    single-use: a successful verification sets used_at, and any
    subsequent presentation of the same token is rejected.
    """
    __tablename__ = "auth_email_verification_tokens"

    id = Column(String, primary_key=True)
    user_id = Column(
        String,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    token_hash = Column(String, nullable=False, unique=True, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    used_at = Column(DateTime(timezone=True), nullable=True)


class AuthOtpRecord(Base):
    """Email OTP record for MFA and any future OTP-based flow.

    The row's `id` is the pending-authentication reference that the
    client submits alongside the code; it is an opaque identifier, not a
    bearer credential, since the OTP code itself is what proves identity.
    The code is never stored in plaintext - only its SHA-256 digest.

    Attempts. `attempt_count` is incremented on every failed verification
    within this record's lifetime. The service layer refuses further
    attempts once the count reaches its configured ceiling, and marks the
    record invalid (used_at set) so a new OTP must be requested. A
    successful verification sets used_at and returns the code to the
    invalidated state, so a second submission of the same code is
    rejected.

    `purpose` distinguishes the flow that issued the OTP. The locked
    scope uses 'login_mfa'; the enum is a plain string so additional
    purposes can be added without a schema change.

    No OTP code is stored here in plaintext or logged anywhere.
    """
    __tablename__ = "auth_otp_records"

    id = Column(String, primary_key=True)
    user_id = Column(
        String,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    purpose = Column(String, nullable=False, index=True)  # e.g. 'login_mfa'
    # SHA-256 hex digest of the OTP code. Deliberately NOT unique: two
    # different flows can legitimately produce the same short code, and
    # lookup always goes through `id` first.
    code_hash = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    used_at = Column(DateTime(timezone=True), nullable=True)
    attempt_count = Column(
        Integer, nullable=False, default=0, server_default=text("0"),
    )
    last_attempt_at = Column(DateTime(timezone=True), nullable=True)
    ip_address = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)

    __table_args__ = (
        # "Find the active OTP for this user and purpose" - used by
        # resend, by progressive attempt tracking, and by any future
        # cleanup job that walks a user's pending OTPs.
        Index(
            "ix_auth_otp_records_user_purpose",
            "user_id", "purpose",
        ),
    )


class AuthAuditEvent(Base):
    """Authentication audit log. One row per auth-relevant event.

    Every row records what happened, when, from where, and for which
    user, so a security investigation can reconstruct an authentication
    history without any access to secrets.

    NEVER contains, in any column or in event_metadata:
      * passwords or password hashes
      * raw JWTs
      * raw refresh tokens
      * OTP codes
      * password-reset tokens
      * email-verification tokens

    event_metadata is a small JSON object for contextual details (the
    failure reason class, the flow name, the client's claimed user-agent
    family, etc.). It is deliberately NOT the raw request body.

    Expected event_type values (service layer is authoritative):
        signup_completed, email_verification_requested,
        email_verification_completed, login_succeeded, login_failed,
        account_locked, otp_requested, otp_verified, otp_failed,
        password_changed, password_reset_requested,
        password_reset_completed, logout, logout_all,
        refresh_token_reuse_detected

    user_id uses ON DELETE SET NULL: the audit history is preserved even
    after the account is removed. Rows with user_id NULL are still
    meaningful (they record the event, just not the identity).
    """
    __tablename__ = "auth_audit_events"

    id = Column(String, primary_key=True)
    user_id = Column(
        String,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    event_type = Column(String, nullable=False, index=True)
    # 'success' | 'failure' - describes the outcome of the event itself.
    # For informational events (logout initiated) this is always
    # 'success'; for outcome-bearing events (login, OTP verification) it
    # distinguishes the two possible results.
    outcome = Column(String, nullable=False)
    ip_address = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)
    event_metadata = Column(_json_type()(), nullable=True)
    created_at = Column(
        DateTime(timezone=True), nullable=False, default=_utcnow, index=True,
    )

    __table_args__ = (
        # "Recent events for this user" and "recent events of this type" -
        # the two shapes the audit view and the security alarms consume.
        Index(
            "ix_auth_audit_events_user_created",
            "user_id", "created_at",
        ),
        Index(
            "ix_auth_audit_events_type_created",
            "event_type", "created_at",
        ),
    )


class Feedback(Base):
    __tablename__ = "feedback"

    id = Column(String, primary_key=True)
    user_id = Column(
        String,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    session_id = Column(
        String, ForeignKey("sessions.session_id", ondelete="CASCADE"),
        nullable=True, index=True,
    )
    rating = Column(Integer, nullable=True)
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)


# ============================================================================
# Documents
# ============================================================================
class GeneratedDocument(Base):
    """Unchanged from prior turn. GeneratedDocument.is_current is a
    separate artifact lifecycle and is NOT part of the unified versioning
    contract."""
    __tablename__ = "generated_documents"

    id = Column(String, primary_key=True)
    session_id = Column(
        String, ForeignKey("sessions.session_id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    phase = Column(String, nullable=False)
    label = Column(String, nullable=False)
    is_current = Column(
        Boolean, nullable=False, default=True,
        server_default=text("true"), index=True,
    )
    filename = Column(String, nullable=False)
    content_type = Column(
        String, nullable=False,
        default="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    content = Column(LargeBinary, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(
        DateTime(timezone=True), nullable=False, default=_utcnow,
        onupdate=_utcnow,
    )

    __table_args__ = (
        Index(
            "ix_generated_documents_session_phase_label",
            "session_id", "phase", "label",
        ),
        Index(
            "ix_generated_documents_session_phase_label_current",
            "session_id", "phase", "label",
            unique=True,
            postgresql_where=text("is_current"),
            sqlite_where=text("is_current"),
        ),
    )


class ProjectDocument(Base):
    """Unchanged from prior turn."""
    __tablename__ = "project_documents"

    id = Column(String, primary_key=True)
    session_id = Column(
        String, ForeignKey("sessions.session_id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    user_id = Column(
        String,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    filename = Column(String, nullable=False)
    storage_key = Column(String, nullable=False, unique=True)
    content_type = Column(String, nullable=False)
    size_bytes = Column(Integer, nullable=False)
    extracted_text_chars = Column(Integer, nullable=False, default=0)
    uploaded_at = Column(
        DateTime(timezone=True), nullable=False, default=_utcnow, index=True,
    )


# ============================================================================
# Project memory
# ============================================================================
class ProjectMemory(Base):
    """Unchanged from prior turn."""
    __tablename__ = "project_memories"

    id = Column(String, primary_key=True)
    session_id = Column(
        String, ForeignKey("sessions.session_id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    category = Column(String, nullable=False, index=True)
    content = Column(Text, nullable=False)
    entry_metadata = Column(_json_type()(), nullable=True)
    tags = Column(_json_type()(), nullable=True)
    importance = Column(Float, nullable=False, default=1.0)
    access_count = Column(Integer, nullable=False, default=0)
    last_accessed = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, index=True)


# ============================================================================
# Project intelligence - structured objects
# ============================================================================
class RequirementItemRecord(Base):
    """UNCHANGED from prior turn. Already carries the partial unique
    index ix_requirement_items_session_external_code_current over
    (session_id, external_code) WHERE is_current."""
    __tablename__ = "requirement_items"

    id = Column(String, primary_key=True)
    session_id = Column(
        String, ForeignKey("sessions.session_id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    lineage_id = Column(String, nullable=False, index=True)
    version = Column(Integer, nullable=False, default=1)
    is_current = Column(Boolean, nullable=False, default=True)
    category = Column(String, nullable=False)
    external_code = Column(String, nullable=True, index=True)
    description = Column(Text, nullable=False)
    priority = Column(String, nullable=False, default="Medium")
    req_type = Column(String, nullable=False, default="Functional")
    acceptance_criteria = Column(Text, nullable=True)
    status = Column(String, nullable=False, default="draft")
    rationale = Column(Text, nullable=True)
    source = Column(Text, nullable=True)
    source_excerpt = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(
        DateTime(timezone=True), nullable=False, default=_utcnow,
        onupdate=_utcnow,
    )

    __table_args__ = (
        Index(
            "ix_requirement_items_session_external_code_current",
            "session_id",
            "external_code",
            unique=True,
            postgresql_where=text("is_current"),
            sqlite_where=text("is_current"),
        ),
        Index(
            "ix_requirement_items_lineage_current",
            "lineage_id",
            unique=True,
            postgresql_where=text("is_current"),
            sqlite_where=text("is_current"),
        ),
    )


class ProcessStepRecord(Base):
    """Structural representation of business process steps, linkable back
    to the requirement(s) they implement.

    UNIFIED VERSIONING CONTRACT (this cycle):

    The canonical business identity of a process step is
    (session_id, external_code). Across regeneration the step keeps the
    same external_code, keeps its lineage_id, increments `version`, the
    previous current row is flipped to is_current=False, and the new row
    is inserted with is_current=True. Historical rows remain queryable and
    are never mutated in place.

    The prior full-table UniqueConstraint on (session_id, external_code)
    - which forbade historical duplicates and made history-over-overwrite
    impossible - has been replaced with a partial unique index over
    (session_id, external_code) WHERE is_current. This is the database's
    authoritative enforcement of "at most one current row per identity",
    and it is also the concurrency boundary: two racing writers cannot
    both leave a current row for the same identity; the second commit
    raises a real PostgreSQL integrity failure.

    requirement_id (singular) is legacy: the domain is many-to-many and
    the canonical storage of step→requirement links is TraceLink. The
    column is retained for backward compatibility. Do not remove it in
    this cycle.
    """
    __tablename__ = "process_steps"

    id = Column(String, primary_key=True)
    session_id = Column(
        String, ForeignKey("sessions.session_id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    lineage_id = Column(String, nullable=False, index=True)
    version = Column(Integer, nullable=False, default=1)
    is_current = Column(Boolean, nullable=False, default=True)
    process_name = Column(String, nullable=False)
    step_number = Column(Integer, nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    responsible_role = Column(String, nullable=True)
    trigger = Column(Text, nullable=True)
    inputs = Column(_json_type()(), nullable=True)
    outputs = Column(_json_type()(), nullable=True)
    transaction = Column(String, nullable=True)
    exception_paths = Column(_json_type()(), nullable=True)
    external_code = Column(String, nullable=True, index=True)
    requirement_id = Column(
        String, ForeignKey("requirement_items.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (
        Index("ix_process_steps_session_process", "session_id", "process_name"),
        # Unified versioning invariant: at most one CURRENT row per
        # (session_id, external_code). Historical versions
        # (is_current=False) are exempt and may retain the same external
        # code indefinitely. Replaces the former full-table
        # UniqueConstraint uq_process_step_session_external_code which
        # made history-over-overwrite impossible.
        Index(
            "ix_process_steps_session_external_code_current",
            "session_id",
            "external_code",
            unique=True,
            postgresql_where=text("is_current"),
            sqlite_where=text("is_current"),
        ),
        # Database-enforced invariant: at most one CURRENT version per
        # lineage. Historical versions (is_current=False) are exempt.
        # Established by migration 598aff673b1b.
        Index(
            "ix_process_steps_lineage_current",
            "lineage_id",
            unique=True,
            postgresql_where=text("is_current"),
            sqlite_where=text("is_current"),
        ),
    )


class SolutionDecision(Base):
    """ERP/module/config/customization/integration decisions as
    structured objects with rationale, linkable to the requirement(s)
    that drove them.

    UNIFIED VERSIONING CONTRACT (this cycle):

    The canonical business identity of a solution decision is
    (session_id, external_code). Across regeneration the decision keeps
    the same external_code, keeps its lineage_id, increments `version`,
    the previous current row is flipped to is_current=False, and the new
    row is inserted with is_current=True. Historical rows remain
    queryable and are never mutated in place.

    Prior to this cycle the model had no unique constraint on
    external_code at all - only ix_solution_decisions_lineage_current on
    lineage_id. That allowed two current rows with the same
    (session_id, external_code) to coexist; the service was relying on
    its own read-then-write pattern, which is not concurrency-safe. The
    new partial unique index ix_solution_decisions_session_external_code_current
    over (session_id, external_code) WHERE is_current is the database's
    authoritative enforcement of "at most one current row per identity"
    and the concurrency boundary for racing regenerations.

    requirement_id (singular) is legacy, as with ProcessStepRecord: the
    many-to-many mapping lives in TraceLink. Do not remove it in this
    cycle.
    """
    __tablename__ = "solution_decisions"

    id = Column(String, primary_key=True)
    session_id = Column(
        String, ForeignKey("sessions.session_id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    lineage_id = Column(String, nullable=False, index=True)
    version = Column(Integer, nullable=False, default=1)
    is_current = Column(Boolean, nullable=False, default=True)
    stage = Column(String, nullable=False, default="proposed")
    decision_type = Column(String, nullable=False)
    component = Column(String, nullable=True)
    description = Column(Text, nullable=False)
    rationale = Column(Text, nullable=True)
    classification = Column(String, nullable=True)
    complexity = Column(String, nullable=True)
    lifecycle_impact = Column(Text, nullable=True)
    external_code = Column(String, nullable=True, index=True)
    requirement_id = Column(
        String, ForeignKey("requirement_items.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    status = Column(String, nullable=False, default="proposed")
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (
        Index("ix_solution_decisions_session_type", "session_id", "decision_type"),
        # Unified versioning invariant: at most one CURRENT row per
        # (session_id, external_code). Historical versions
        # (is_current=False) are exempt. NEW in this cycle - previously
        # the database did not enforce this and the service relied on an
        # unprotected read-then-write.
        Index(
            "ix_solution_decisions_session_external_code_current",
            "session_id",
            "external_code",
            unique=True,
            postgresql_where=text("is_current"),
            sqlite_where=text("is_current"),
        ),
        # Database-enforced invariant: at most one CURRENT version per
        # lineage. Established by migration 8b69bcaa614c.
        Index(
            "ix_solution_decisions_lineage_current",
            "lineage_id",
            unique=True,
            postgresql_where=text("is_current"),
            sqlite_where=text("is_current"),
        ),
    )


class TestCaseRecord(Base):
    """Structured QA / UAT test cases.

    CANONICAL IDENTITY: (session_id, test_type, external_code).

    `test_type` is part of the key because QA and UAT both emit short
    sequential external codes (TC-001, TC-002, ...) per generation; the
    same session may hold a QA case TC-001 and a UAT case TC-001 as
    distinct rows, and both must coexist. The writer
    (sync_test_cases_from_structured) upserts on exactly this triple via
    PostgreSQL INSERT ... ON CONFLICT (session_id, test_type,
    external_code) DO UPDATE, so the constraint below is also the index
    used for conflict resolution and no additional index is required.

    Test cases are NOT versioned: there is no lineage_id / version /
    is_current column here, unlike RequirementItemRecord,
    ProcessStepRecord, and SolutionDecision. Regeneration updates the
    existing row's content fields in place, preserving its physical id,
    created_at, and needs_retest flag. That statefulness is why
    history-over-overwrite does not apply to this table.

    The prior full-table UniqueConstraint uq_test_case_session_external_code
    over (session_id, external_code) was incorrect - it prevented QA and
    UAT from coexisting under a shared code namespace. It is replaced by
    uq_test_case_session_type_external_code, which reflects the actual
    identity of a test case.
    """
    __tablename__ = "test_case_records"

    id = Column(String, primary_key=True)
    session_id = Column(
        String, ForeignKey("sessions.session_id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    test_type = Column(String, nullable=False)
    external_code = Column(String, nullable=True)
    scenario = Column(String, nullable=False)
    priority = Column(String, nullable=False, default="Medium")
    expected_result = Column(Text, nullable=True)
    user_role = Column(String, nullable=True)
    business_process = Column(String, nullable=True)
    acceptance_criteria = Column(Text, nullable=True)
    related_design_component = Column(String, nullable=True)
    needs_retest = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(
        DateTime(timezone=True), nullable=False, default=_utcnow,
        onupdate=_utcnow,
    )

    __table_args__ = (
        # Canonical identity of a test case. Also serves as the index
        # used by the ON CONFLICT clause in sync_test_cases_from_structured.
        # The column order matters for PostgreSQL's ON CONFLICT
        # inference and must match the writer.
        UniqueConstraint("session_id", "test_type", "external_code",
                         name="uq_test_case_session_type_external_code"),
    )


class TrainingStepRecord(Base):
    """Structured training manual steps.

    CANONICAL IDENTITY: (session_id, external_code).

    Training steps are NOT versioned: there is no lineage_id / version /
    is_current column here. Regeneration updates the existing row's
    content fields in place (title, instructions, role, verification,
    prerequisites), preserving its physical id and created_at. This
    matches the contract implemented by
    sync_training_steps_from_structured in the service layer.

    The unique constraint uq_training_step_session_external_code is
    therefore correct as-is and is not changed by the test-case
    reconciliation migration.
    """
    __tablename__ = "training_step_records"

    id = Column(String, primary_key=True)
    session_id = Column(
        String, ForeignKey("sessions.session_id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    external_code = Column(String, nullable=True, index=True)
    title = Column(String, nullable=False)
    instructions = Column(Text, nullable=True)
    role = Column(String, nullable=True)
    verification = Column(Text, nullable=True)
    prerequisites = Column(_json_type()(), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(
        DateTime(timezone=True), nullable=False, default=_utcnow,
        onupdate=_utcnow,
    )

    __table_args__ = (
        UniqueConstraint("session_id", "external_code",
                         name="uq_training_step_session_external_code"),
    )


# ============================================================================
# Issues, reviews, traceability
# ============================================================================
class ProjectIssue(Base):
    """Unchanged from prior turn."""
    __tablename__ = "project_issues"

    id = Column(String, primary_key=True)
    session_id = Column(
        String, ForeignKey("sessions.session_id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    issue_type = Column(String, nullable=False)
    severity = Column(String, nullable=False, default="medium")
    description = Column(Text, nullable=False)
    related_object_type = Column(String, nullable=True)
    related_object_id = Column(String, nullable=True)
    test_case_id = Column(
        String, ForeignKey("test_case_records.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    classification = Column(String, nullable=True)
    status = Column(String, nullable=False, default="open")
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(
        DateTime(timezone=True), nullable=False, default=_utcnow,
        onupdate=_utcnow,
    )
    resolved_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_project_issues_session_status", "session_id", "status"),
        Index("ix_project_issues_session_type", "session_id", "issue_type"),
    )


class ReviewAction(Base):
    """Unchanged from prior turn."""
    __tablename__ = "review_actions"

    id = Column(String, primary_key=True)
    session_id = Column(
        String, ForeignKey("sessions.session_id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    user_id = Column(
        String,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    object_type = Column(String, nullable=False)
    object_id = Column(String, nullable=False)
    action = Column(String, nullable=False)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (
        Index("ix_review_actions_object", "object_type", "object_id"),
    )


class TraceLink(Base):
    """Unchanged from prior turn. TraceLink.source_id/target_id are
    physical row IDs of the versioned entities. Historical versions
    remain addressable by their physical IDs; regeneration does NOT
    repoint existing trace links - this is the existing domain contract
    and this cycle does not change it."""
    __tablename__ = "trace_links"

    id = Column(String, primary_key=True)
    session_id = Column(
        String, ForeignKey("sessions.session_id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    source_type = Column(String, nullable=False)
    source_id = Column(String, nullable=False)
    target_type = Column(String, nullable=False)
    target_id = Column(String, nullable=False)
    relationship = Column(String, nullable=False, default="covers")
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (
        Index("ix_trace_links_target", "target_type", "target_id"),
        Index("ix_trace_links_source", "source_type", "source_id"),
        Index("ix_trace_links_session_relationship", "session_id", "relationship"),
        UniqueConstraint(
            "session_id", "source_type", "source_id",
            "target_type", "target_id", "relationship",
            name="uq_trace_link_edge",
        ),
    )


# ============================================================================
# Baselines
# ============================================================================
class SolutionBaseline(Base):
    """Unchanged from prior turn."""
    __tablename__ = "solution_baselines"

    id = Column(String, primary_key=True)
    session_id = Column(
        String, ForeignKey("sessions.session_id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    label = Column(String, nullable=False)
    notes = Column(Text, nullable=True)
    created_by = Column(String, ForeignKey("users.id"), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)


class SolutionBaselineItem(Base):
    """Unchanged from prior turn. SolutionBaselineItem.solution_decision_id
    points to a specific physical versioned row; historical versions
    remain addressable. This cycle does not change baseline semantics."""
    __tablename__ = "solution_baseline_items"

    id = Column(String, primary_key=True)
    baseline_id = Column(
        String,
        ForeignKey("solution_baselines.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    solution_decision_id = Column(
        String,
        ForeignKey("solution_decisions.id", ondelete="CASCADE"),
        nullable=False,
    )