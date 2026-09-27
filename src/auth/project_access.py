"""
Project-membership and per-artifact grant authorization.

Two authorization axes meet here, and this module composes them:

  * Project membership. Derived, not stored. A personal project's member
    is its `sessions.user_id`; an organization-owned project's members
    are the members of the owning organization. This mirrors the
    two-case rule already implemented by `_get_owned_session` in
    orchestrator_api.py, and is exposed as `is_project_member` so
    artifact-grant helpers can consult it without duplicating the rule.

  * Per-user artifact grant. Stored in `session_user_artifact_grants`
    (see src/db/models.py). Answers "which artifacts of this project
    may this already-a-member access?". A grant does not establish
    membership; it is only consulted after membership has been
    established.

Design notes
------------
  * No FastAPI imports. No session opening. Every function takes an
    explicit SQLAlchemy Session. This keeps the module usable from route
    handlers (which have a session via Depends(get_db)) and from
    short-lived contexts.

  * Application capability remains separate. Whether the caller has the
    application-level right to invoke a route is decided by
    `require_permission(...)` (src/auth/guards.py). Whether the caller
    can reach a specific project's specific artifact is decided here.

  * Failure is False, not exception. `is_project_member`,
    `user_has_artifact_access`, `user_is_frd_signatory`, and
    `user_is_uat_participant` all return booleans. Callers map False to
    their route's failure contract (typically 404, matching the existing
    enumeration-resistant tenant-boundary behavior). Only the mutation
    helpers (`create_grant`, `revoke_grant`) raise, and only for
    programmer error or precondition violation, since a route that
    reaches those has already passed a `PROJECT_GRANTS_MANAGE` guard
    and is expected to handle ValueError as a 400.

  * Revocation is soft. Revoked rows retain `revoked_at` and
    `revoked_by_user_id`. A later regrant creates a new active row; the
    historical revoked row remains queryable for audit.

  * Designation coherence is enforced at both layers. The DB CHECK
    constraints reject an incoherent row even if a future caller
    bypasses these helpers. `create_grant` rejects the same
    incoherence up front with a clear error, so a caller cannot trigger
    the DB error by accident.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from sqlalchemy.orm import Session

from src.auth.rbac import has_active_membership
from src.db.models import (
    OrganizationMembership,
    SessionRecord,
    SessionUserArtifactGrant,
    User,
    UserRoleRecord,
)


class ArtifactType(str, Enum):
    """The four artifact categories currently grantable to an ERP User.

    String-valued, not a Postgres ENUM, matching the pattern used by
    decision_type / test_type / issue_type elsewhere in the schema so
    new artifact types can be added without an ALTER TYPE migration.
    """
    REQUIREMENTS_QUESTIONNAIRE = "requirements_questionnaire"
    FRD = "frd"
    UAT_SCENARIOS = "uat_scenarios"
    TRAINING_MATERIALS = "training_materials"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _artifact_value(artifact_type: ArtifactType | str) -> str:
    """Coerce an ArtifactType or string to its canonical string value.

    Rejects unknown values up front rather than letting an unrelated
    lookup silently return no match - a typo in a caller's string should
    surface as a clear error, not as a silent denial of access.

    Accepts an ArtifactType enum or a plain string so callers can pass
    the wire-format string straight through from an API payload.
    """
    if isinstance(artifact_type, ArtifactType):
        return artifact_type.value
    try:
        return ArtifactType(artifact_type).value
    except (ValueError, TypeError):
        raise ValueError(f"Unknown artifact type: {artifact_type!r}")


# ---------------------------------------------------------------------------
# Membership
# ---------------------------------------------------------------------------
def is_project_member(db: Session, session_id: str, user_id: str) -> bool:
    """True iff `user_id` is a member of `session_id`.

    Mirrors `_get_owned_session` (orchestrator_api.py) semantics exactly:

      * personal project (organization_id IS NULL):
            session.user_id == user_id
      * organization-owned project (organization_id IS NOT NULL):
            an active OrganizationMembership exists for the user in the
            owning organization. session.user_id is NOT consulted.

    A missing project is False, not an exception. Callers map False to
    their route's failure contract.
    """
    session = db.get(SessionRecord, session_id)
    if session is None:
        return False
    if session.organization_id is None:
        return session.user_id == user_id
    return has_active_membership(db, user_id, session.organization_id)


# ---------------------------------------------------------------------------
# Grants
# ---------------------------------------------------------------------------
def get_active_grant(
    db: Session,
    session_id: str,
    user_id: str,
    artifact_type: ArtifactType | str,
) -> Optional[SessionUserArtifactGrant]:
    """Return the active (non-revoked) grant for this identity, or None.

    Raises ValueError for an unknown artifact_type string - a typo in
    the caller should surface loudly, not silently deny access.
    """
    value = _artifact_value(artifact_type)
    return (
        db.query(SessionUserArtifactGrant)
        .filter(
            SessionUserArtifactGrant.session_id == session_id,
            SessionUserArtifactGrant.user_id == user_id,
            SessionUserArtifactGrant.artifact_type == value,
            SessionUserArtifactGrant.revoked_at.is_(None),
        )
        .first()
    )


def user_has_artifact_access(
    db: Session,
    session_id: str,
    user_id: str,
    artifact_type: ArtifactType | str,
) -> bool:
    """True iff `user_id` is a project member AND holds an active grant
    for the given artifact on that project.

    Two conditions, both required:
      1. `is_project_member(db, session_id, user_id)` is True.
      2. An active `session_user_artifact_grants` row exists for
         (session_id, user_id, artifact_type).

    Membership is checked first so a grant left over from a revoked
    membership is not treated as access. In a correct data model this
    cannot happen (membership revocation and grant revocation are
    independent operations), but the check order is defensive.
    """
    if not is_project_member(db, session_id, user_id):
        return False
    return get_active_grant(db, session_id, user_id, artifact_type) is not None


def user_is_frd_signatory(db: Session, session_id: str, user_id: str) -> bool:
    """True iff `user_id` is a project member AND holds an active FRD
    grant AND the grant carries is_signatory=True.

    Signatory status is a designation on top of ordinary FRD visibility,
    not a substitute for it: a user without an FRD grant is not a
    signatory, and a user with an FRD grant but is_signatory=False is
    not a signatory either.
    """
    if not is_project_member(db, session_id, user_id):
        return False
    grant = get_active_grant(db, session_id, user_id, ArtifactType.FRD)
    return grant is not None and bool(grant.is_signatory)


def user_is_uat_participant(db: Session, session_id: str, user_id: str) -> bool:
    """True iff `user_id` is a project member AND holds an active UAT
    scenarios grant AND the grant carries is_uat_participant=True.

    UAT participant status implies UAT scenarios access; it does not
    grant general testing access (TESTING_READ), which remains a role
    capability.
    """
    if not is_project_member(db, session_id, user_id):
        return False
    grant = get_active_grant(db, session_id, user_id, ArtifactType.UAT_SCENARIOS)
    return grant is not None and bool(grant.is_uat_participant)


# ---------------------------------------------------------------------------
# Mutation
# ---------------------------------------------------------------------------
def create_grant(
    db: Session,
    session_id: str,
    grantee_user_id: str,
    artifact_type: ArtifactType | str,
    granted_by_user_id: str,
    is_signatory: bool = False,
    is_uat_participant: bool = False,
) -> SessionUserArtifactGrant:
    """Grant (or update) an artifact access grant.

    Behaviour:

      * Rejects the call if the grantee is not a member of the project.
        The grant model does not establish membership; membership must
        already exist through the personal-owner rule or an
        OrganizationMembership.

      * Rejects designation/artifact incoherence up front:
          is_signatory        -> artifact_type must be 'frd'
          is_uat_participant  -> artifact_type must be 'uat_scenarios'
        The same invariants are enforced by DB CHECK constraints; the
        helper check produces a clearer error than a raw IntegrityError.

      * Idempotent on re-grant. If an active grant already exists for
        (session, user, artifact), the existing row is returned. If the
        designation flags differ from the caller's request, they are
        updated in place; the grant's granted_at and granted_by_user_id
        are preserved. This treats "the user has FRD access" as one
        grant whose designation may evolve, rather than requiring a
        revoke/regrant cycle to change a flag.

    Does NOT commit. Callers commit as part of a larger transaction.
    """
    value = _artifact_value(artifact_type)

    if not is_project_member(db, session_id, grantee_user_id):
        raise ValueError(
            "Cannot grant artifact access: grantee is not a member of "
            "the project. Establish project membership first."
        )

    if is_signatory and value != ArtifactType.FRD.value:
        raise ValueError(
            "is_signatory is only valid for the FRD artifact; got "
            f"artifact_type={value!r}."
        )
    if is_uat_participant and value != ArtifactType.UAT_SCENARIOS.value:
        raise ValueError(
            "is_uat_participant is only valid for the UAT scenarios "
            f"artifact; got artifact_type={value!r}."
        )

    existing = get_active_grant(db, session_id, grantee_user_id, value)
    if existing is not None:
        # Update designations in place if they differ.
        if existing.is_signatory != is_signatory:
            existing.is_signatory = is_signatory
        if existing.is_uat_participant != is_uat_participant:
            existing.is_uat_participant = is_uat_participant
        return existing

    grant = SessionUserArtifactGrant(
        id=uuid.uuid4().hex,
        session_id=session_id,
        user_id=grantee_user_id,
        artifact_type=value,
        is_signatory=is_signatory,
        is_uat_participant=is_uat_participant,
        granted_by_user_id=granted_by_user_id,
        granted_at=_utcnow(),
    )
    db.add(grant)
    return grant


def revoke_grant(
    db: Session,
    session_id: str,
    grantee_user_id: str,
    artifact_type: ArtifactType | str,
    revoked_by_user_id: str,
) -> bool:
    """Soft-revoke the active grant for this identity.

    Sets revoked_at and revoked_by_user_id on the currently-active row.
    The row is not deleted, so the historical record survives and a
    later regrant creates a fresh active row.

    Idempotent: returns False if there is no active grant to revoke
    (either the grant never existed, or it has already been revoked).
    Does NOT commit. Callers commit as part of a larger transaction.
    """
    value = _artifact_value(artifact_type)
    existing = get_active_grant(db, session_id, grantee_user_id, value)
    if existing is None:
        return False
    existing.revoked_at = _utcnow()
    existing.revoked_by_user_id = revoked_by_user_id
    return True

# ---------------------------------------------------------------------------
# Listing (read-only helpers for the grant-management API)
# ---------------------------------------------------------------------------
def list_active_grants(
    db: Session, session_id: str,
) -> list[SessionUserArtifactGrant]:
    """Every active grant on this project, newest first.

    Active is `revoked_at IS NULL`. Ordering is by granted_at descending
    so the consultant's grant table is stable across reloads and the
    newest row appears first.
    """
    return (
        db.query(SessionUserArtifactGrant)
        .filter(
            SessionUserArtifactGrant.session_id == session_id,
            SessionUserArtifactGrant.revoked_at.is_(None),
        )
        .order_by(SessionUserArtifactGrant.granted_at.desc())
        .all()
    )


def list_revoked_grants(
    db: Session, session_id: str,
) -> list[SessionUserArtifactGrant]:
    """Every revoked grant on this project, most recently revoked first.

    Audit view. Rows are never deleted by normal flows, so this list
    grows monotonically and every regrant leaves its predecessor here.
    """
    return (
        db.query(SessionUserArtifactGrant)
        .filter(
            SessionUserArtifactGrant.session_id == session_id,
            SessionUserArtifactGrant.revoked_at.is_not(None),
        )
        .order_by(SessionUserArtifactGrant.revoked_at.desc())
        .all()
    )


def list_eligible_erp_users(
    db: Session, session_id: str,
) -> list[dict]:
    """Eligible ERP User assignment pool for a project.

    Organization-owned project: members of the owning organization who
    hold the `erp_user` application role. A user can only be a recipient
    of an artifact grant if they are already a project member, so this
    list is exactly the set of users create_grant would accept.

    Personal project: empty list. A personal project's only member is
    its owner, and the owner is not an ERP User assignment target; the
    grant model is not meaningful for a project with a single member.
    Returning an empty list is the truthful answer, not a policy
    denial — the frontend renders an explicit empty state.

    A missing session is also an empty list. The caller has already
    passed require_project_grant_management, so a missing session means
    it was deleted concurrently; no useful error is possible here.

    Result shape matches the frontend `EligibleErpUser` type:
        {user_id, email, name, org_role}
    """
    session = db.get(SessionRecord, session_id)
    if session is None or session.organization_id is None:
        return []

    rows = (
        db.query(User, OrganizationMembership.role)
        .join(
            OrganizationMembership,
            OrganizationMembership.user_id == User.id,
        )
        .join(
            UserRoleRecord,
            UserRoleRecord.user_id == User.id,
        )
        .filter(
            OrganizationMembership.organization_id == session.organization_id,
            UserRoleRecord.role == "erp_user",
        )
        .order_by(User.email.asc())
        .all()
    )

    seen: set[str] = set()
    out: list[dict] = []
    for user, org_role in rows:
        if user.id in seen:
            continue
        seen.add(user.id)
        out.append({
            "user_id": user.id,
            "email": user.email,
            "name": user.name,
            "org_role": org_role,
        })
    return out