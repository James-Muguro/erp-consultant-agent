"""Grant-management endpoints.

Every route chains require_project_grant_management (which combines the
permission check, the personal-owner exception, and the tenant boundary
into one factory) — endpoints never independently combine
require_permission with _get_owned_session for this route group.
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.auth.dependencies import get_db
from src.auth.guards import require_project_grant_management
from src.auth.project_access import (
    ArtifactType,
    create_grant,
    is_project_member,
    list_active_grants,
    list_eligible_erp_users,
    list_revoked_grants,
    revoke_grant,
)
from src.db.models import SessionUserArtifactGrant, User


router = APIRouter(
    prefix="/api/projects/{session_id}/grants",
    tags=["grants"],
)


def _serialize_grant(
    g: SessionUserArtifactGrant, email_lookup: dict[str, dict],
) -> Dict[str, Any]:
    grantee = email_lookup.get(g.user_id, {})
    granter = email_lookup.get(g.granted_by_user_id or "", {})
    revoker = email_lookup.get(g.revoked_by_user_id or "", {})
    return {
        "id": g.id,
        "user_id": g.user_id,
        "user_email": grantee.get("email"),
        "user_name": grantee.get("name"),
        "artifact_type": g.artifact_type,
        "is_signatory": bool(g.is_signatory),
        "is_uat_participant": bool(g.is_uat_participant),
        "granted_at": g.granted_at.isoformat() if g.granted_at else None,
        "granted_by_user_id": g.granted_by_user_id,
        "granted_by_email": granter.get("email"),
        "revoked_at": g.revoked_at.isoformat() if g.revoked_at else None,
        "revoked_by_user_id": g.revoked_by_user_id,
        "revoked_by_email": revoker.get("email"),
    }


def _build_email_lookup(db: Session, user_ids: set[str]) -> dict[str, dict]:
    if not user_ids:
        return {}
    rows = db.query(User).filter(User.id.in_(user_ids)).all()
    return {u.id: {"email": u.email, "name": u.name} for u in rows}


# ---------------------------------------------------------------------------
# Eligible ERP Users
# ---------------------------------------------------------------------------
@router.get("/eligible-erp-users")
def eligible_erp_users(
    session_id: str,
    current_user: User = Depends(require_project_grant_management()),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return {"users": list_eligible_erp_users(db, session_id)}


# ---------------------------------------------------------------------------
# Active grants
# ---------------------------------------------------------------------------
@router.get("")
def list_grants(
    session_id: str,
    current_user: User = Depends(require_project_grant_management()),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    grants = list_active_grants(db, session_id)
    ids: set[str] = set()
    for g in grants:
        ids.add(g.user_id)
        if g.granted_by_user_id:
            ids.add(g.granted_by_user_id)
    lookup = _build_email_lookup(db, ids)
    return {"grants": [_serialize_grant(g, lookup) for g in grants]}


# ---------------------------------------------------------------------------
# Revoked grants (history)
# ---------------------------------------------------------------------------
@router.get("/history")
def list_grant_history(
    session_id: str,
    current_user: User = Depends(require_project_grant_management()),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    grants = list_revoked_grants(db, session_id)
    ids: set[str] = set()
    for g in grants:
        ids.add(g.user_id)
        if g.granted_by_user_id:
            ids.add(g.granted_by_user_id)
        if g.revoked_by_user_id:
            ids.add(g.revoked_by_user_id)
    lookup = _build_email_lookup(db, ids)
    return {"grants": [_serialize_grant(g, lookup) for g in grants]}


# ---------------------------------------------------------------------------
# Create / update
# ---------------------------------------------------------------------------
class CreateGrantBody(BaseModel):
    user_id: str
    artifact_type: str
    is_signatory: bool = False
    is_uat_participant: bool = False


@router.post("")
def upsert_grant(
    session_id: str,
    body: CreateGrantBody,
    current_user: User = Depends(require_project_grant_management()),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    try:
        ArtifactType(body.artifact_type)
    except ValueError:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Unknown artifact type: {body.artifact_type}",
        )
    if not is_project_member(db, session_id, body.user_id):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Target user is not a project member.",
        )
    try:
        grant = create_grant(
            db,
            session_id=session_id,
            grantee_user_id=body.user_id,
            artifact_type=body.artifact_type,
            granted_by_user_id=current_user.id,
            is_signatory=body.is_signatory,
            is_uat_participant=body.is_uat_participant,
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    lookup = _build_email_lookup(db, {grant.user_id, current_user.id})
    payload = _serialize_grant(grant, lookup)
    db.commit()
    return payload


# ---------------------------------------------------------------------------
# Revoke
# ---------------------------------------------------------------------------
@router.delete("/{user_id}/{artifact_type}")
def revoke(
    session_id: str,
    user_id: str,
    artifact_type: str,
    current_user: User = Depends(require_project_grant_management()),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    try:
        ArtifactType(artifact_type)
    except ValueError:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Unknown artifact type: {artifact_type}",
        )
    revoked = revoke_grant(
        db,
        session_id=session_id,
        grantee_user_id=user_id,
        artifact_type=artifact_type,
        revoked_by_user_id=current_user.id,
    )
    db.commit()
    return {"revoked": bool(revoked)}