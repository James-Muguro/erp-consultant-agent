"""
Database-backed queries for the RBAC layer.

Every function here takes an explicit SQLAlchemy Session. None of them
open their own - the callers decide transaction scope. This keeps the
module usable from FastAPI request handlers (which have a session via
Depends(get_db)) and from short-lived contexts (like the tenant check
inside _get_owned_session, which opens its own session on demand).

Naming: the ORM model for the user_roles table is `UserRoleRecord`, not
`UserRole`, to avoid a name collision with the UserRole application-role
enum in permissions.py.
"""
from __future__ import annotations

import uuid
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from src.auth.permissions import (
    OrganizationPrivilege,
    OrganizationRole,
    Permission,
    ROLE_PERMISSIONS,
    ORG_ROLE_PRIVILEGES,
    UserRole,
)
from src.db.models import (
    Organization,
    OrganizationMembership,
    UserRoleRecord,
)


# ---------------------------------------------------------------------------
# User roles and effective permissions
# ---------------------------------------------------------------------------
def get_user_roles(db: Session, user_id: str) -> List[UserRole]:
    """Return the application roles the user holds.

    Unknown role strings in the DB are silently skipped (defensive - a
    role value removed from the enum after data was written should not
    crash every authenticated request for that user).
    """
    rows = (
        db.query(UserRoleRecord.role)
        .filter(UserRoleRecord.user_id == user_id)
        .all()
    )
    out: List[UserRole] = []
    for (role_value,) in rows:
        try:
            out.append(UserRole(role_value))
        except ValueError:
            continue
    return out


def get_user_permissions(db: Session, user_id: str) -> frozenset:
    """Effective permission set for a user: the union of the permission
    sets of every application role they hold."""
    roles = get_user_roles(db, user_id)
    out: set = set()
    for r in roles:
        out.update(ROLE_PERMISSIONS.get(r, frozenset()))
    return frozenset(out)


def user_has_permission(db: Session, user_id: str, permission: Permission) -> bool:
    return permission in get_user_permissions(db, user_id)


def grant_role(db: Session, user_id: str, role: UserRole) -> UserRoleRecord:
    """Grant an application role. Idempotent - if the (user_id, role) pair
    already exists, the existing row is returned unchanged.

    Callers are responsible for the commit; this helper does not commit,
    so it can participate in a larger signup transaction.
    """
    existing = (
        db.query(UserRoleRecord)
        .filter(
            UserRoleRecord.user_id == user_id,
            UserRoleRecord.role == role.value,
        )
        .first()
    )
    if existing is not None:
        return existing
    row = UserRoleRecord(
        id=uuid.uuid4().hex,
        user_id=user_id,
        role=role.value,
    )
    db.add(row)
    return row


# ---------------------------------------------------------------------------
# Organization membership
# ---------------------------------------------------------------------------
def get_membership(
    db: Session, user_id: str, organization_id: str,
) -> Optional[OrganizationMembership]:
    """Return the membership row for (user, org), or None.

    v1 has no soft-delete or 'inactive' state for memberships - a
    membership exists or it does not. The word 'active' in the agreed
    architecture is a value, not a schema feature: leaving an org is a
    row deletion.
    """
    if not organization_id:
        return None
    return (
        db.query(OrganizationMembership)
        .filter(
            OrganizationMembership.user_id == user_id,
            OrganizationMembership.organization_id == organization_id,
        )
        .first()
    )


def has_active_membership(
    db: Session, user_id: str, organization_id: str,
) -> bool:
    return get_membership(db, user_id, organization_id) is not None


def get_membership_role(membership: OrganizationMembership) -> OrganizationRole:
    try:
        return OrganizationRole(membership.role)
    except ValueError:
        return OrganizationRole.MEMBER


def membership_has_privilege(
    membership: OrganizationMembership, privilege: OrganizationPrivilege,
) -> bool:
    role = get_membership_role(membership)
    return privilege in ORG_ROLE_PRIVILEGES.get(role, frozenset())


def list_organizations_for_user(
    db: Session, user_id: str,
) -> List[Tuple[Organization, OrganizationMembership]]:
    """Every (Organization, OrganizationMembership) pair for the user,
    ordered by organization name.

    Returns pairs rather than bare membership rows because callers (the
    /me response builder) need the organization's display name. The
    alternative - a per-membership second query to fetch the org - would
    be an N+1 against a list that is normally short but is unbounded in
    the schema.
    """
    return (
        db.query(Organization, OrganizationMembership)
        .join(
            Organization,
            Organization.id == OrganizationMembership.organization_id,
        )
        .filter(OrganizationMembership.user_id == user_id)
        .order_by(Organization.name)
        .all()
    )


# ---------------------------------------------------------------------------
# Organization creation
# ---------------------------------------------------------------------------
def create_organization(
    db: Session, name: str, owner_user_id: str,
) -> Organization:
    """Create an organization and its initial Owner membership.

    Does not commit - the caller (signup handler) commits as part of a
    larger transaction so a partial failure leaves no orphan organization
    without its owner, and no owner without its organization.
    """
    clean_name = (name or "").strip()
    if not clean_name:
        raise ValueError("Organization name must be non-empty")

    org = Organization(
        id=uuid.uuid4().hex,
        name=clean_name,
        created_by=owner_user_id,
    )
    db.add(org)

    membership = OrganizationMembership(
        id=uuid.uuid4().hex,
        organization_id=org.id,
        user_id=owner_user_id,
        role=OrganizationRole.OWNER.value,
    )
    db.add(membership)
    return org