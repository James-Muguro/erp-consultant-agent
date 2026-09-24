"""
FastAPI dependency factories that combine identity resolution with
authorization checks.

Two separate factories, because the two axes are separate:

  * require_permission(Permission.X) — application-level feature
    permission. Fails with 403 if the user lacks the permission.

  * require_org_privilege(OrganizationPrivilege.X) — organization
    administrative privilege. Fails with 404 if the user is not a member
    of the organization (to preserve the non-leak behavior — the caller
    cannot distinguish 'no such org' from 'not a member'), and with 403
    if they are a member but lack the privilege.

Both factories return the authenticated User (or, for org privileges,
the OrganizationMembership), so route handlers that replace
`Depends(get_current_user)` with `Depends(require_permission(...))`
still get the identity object they need.

A route that operates on organization-owned data will typically use
BOTH: require_permission for the feature, plus the tenant boundary check
inside _get_owned_session in orchestrator_api.py. The two checks are
independent and both must pass.
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from src.auth.dependencies import get_current_user, get_db
from src.auth.permissions import (
    OrganizationPrivilege,
    Permission,
)
from src.auth.rbac import (
    get_membership,
    membership_has_privilege,
    user_has_permission,
)
from src.db.models import OrganizationMembership, User


def require_permission(permission: Permission):
    """Dependency factory: require an application-level permission.

    Usage:
        @app.get("/x")
        def route(
            current_user: User = Depends(require_permission(Permission.X)),
            db: Session = Depends(get_db),
        ):
            ...

    The dependency returns the resolved User so route bodies keep their
    existing `current_user` parameter. FastAPI deduplicates the
    underlying get_db call between this dependency and any route-level
    Depends(get_db), so no extra DB connection is opened.
    """
    def dep(
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        if not user_has_permission(db, current_user.id, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to perform this action.",
            )
        return current_user
    return dep


def require_org_privilege(privilege: OrganizationPrivilege):
    """Dependency factory: require an organization administrative privilege.

    The dependency reads `org_id` from the route path. The route must
    declare a path parameter named exactly `org_id` for FastAPI to
    inject it — this is FastAPI's documented mechanism for shared path
    parameters in dependencies.

    Returns the resolved OrganizationMembership so routes can read the
    caller's role in the org without a second query.
    """
    def dep(
        org_id: str,
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> OrganizationMembership:
        membership = get_membership(db, current_user.id, org_id)
        if membership is None:
            # 404 (not 403) so a caller without access cannot distinguish
            # 'org does not exist' from 'org exists but you are not a
            # member'. This matches the D4 decision on tenant isolation.
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Organization not found",
            )
        if not membership_has_privilege(membership, privilege):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to manage this organization.",
            )
        return membership
    return dep