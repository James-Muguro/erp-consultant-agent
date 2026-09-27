"""Opportunity / TOR workflow endpoints.


All routes require an Opportunity-scoped capability and organization
membership. Cross-organization access returns 404.
"""
from __future__ import annotations


import uuid
from typing import Any, Dict, Optional


from fastapi import (
    APIRouter, Depends, File, HTTPException, Response, UploadFile, status,
)
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session


from src.auth.dependencies import get_current_user, get_db
from src.auth.guards import require_permission
from src.auth.permissions import Permission
from src.auth.rbac import get_membership
from src.db.models import Opportunity, User
from src.services import opportunity_service as svc
from src.services import tor_extraction
from src.storage import object_storage
from src.storage.object_storage import ObjectStorageError, ObjectStorageNotConfigured
from src.tools.document_generator import doc_generator



router = APIRouter(prefix="/api/opportunities", tags=["opportunities"])



# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------
def _require_org_membership(db: Session, user_id: str, org_id: str) -> None:
    """404 if the caller is not a member of the owning organization.
    Matches the enumeration-resistant pattern used elsewhere."""
    if get_membership(db, user_id, org_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Opportunity not found")



def _load_owned_opportunity(
    db: Session, opportunity_id: str, user_id: str,
) -> Opportunity:
    opp = svc.get_opportunity(db, opportunity_id)
    if opp is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Opportunity not found")
    _require_org_membership(db, user_id, opp.organization_id)
    return opp



def _load_owned_opportunity_locked(
    db: Session, opportunity_id: str, user_id: str,
) -> Opportunity:
    """Like `_load_owned_opportunity`, but takes a row-level lock on the
    Opportunity row for the duration of the current transaction.

    Used only by the Mark-as-Won endpoint. Without the lock, two
    concurrent Mark-as-Won requests for the same opportunity both pass
    the state guards in `svc.mark_won` against their own pre-commit
    snapshots and both attempt the conversion. The UNIQUE constraint on
    `opportunities.converted_session_id` rejects the second commit, but
    that surfaces as a raw IntegrityError -> 500 rather than a clean
    409.

    `SELECT ... FOR UPDATE` serializes the two requests: the second
    waits for the first to commit or roll back, then re-reads the row
    (now `status = 'won'`) and is rejected by the state guard inside
    `svc.mark_won` with a clean ValueError -> 409. The lock is held
    until the transaction commits or rolls back, which for this endpoint
    is the same single `db.commit()` that also performs the conversion.

    Membership check runs after the lock is acquired so the caller
    cannot bypass it.

    `with_for_update()` is a no-op on SQLite and the intended behavior
    on PostgreSQL, matching the concurrency pattern already used in
    `src/auth/flows.py` for OTP verification and refresh-token rotation.
    """
    opp = (
        db.query(Opportunity)
        .filter(Opportunity.id == opportunity_id)
        .with_for_update()
        .first()
    )
    if opp is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Opportunity not found")
    _require_org_membership(db, user_id, opp.organization_id)
    return opp


def _serialize_opportunity(opp: Opportunity) -> Dict[str, Any]:
    return {
        "id": opp.id,
        "organization_id": opp.organization_id,
        "title": opp.title,
        "client_name": opp.client_name,
        "status": opp.status,
        "assigned_consultant_user_id": opp.assigned_consultant_user_id,
        "converted_session_id": opp.converted_session_id,
        "owner_user_id": opp.owner_user_id,
        "created_by_user_id": opp.created_by_user_id,
        "created_at": opp.created_at.isoformat() if opp.created_at else None,
        "updated_at": opp.updated_at.isoformat() if opp.updated_at else None,
        "won_at": opp.won_at.isoformat() if opp.won_at else None,
    }



def _serialize_requirement(r) -> Dict[str, Any]:
    return {
        "id": r.id,
        "opportunity_id": r.opportunity_id,
        "external_code": r.external_code,
        "category": r.category,
        "description": r.description,
        "priority": r.priority,
        "req_type": r.req_type,
        "acceptance_criteria": r.acceptance_criteria,
        "status": r.status,
        "importance": r.importance,
        "fit_response": r.fit_response,
        "fit_response_ai": r.fit_response_ai,
        "fit_response_comment": r.fit_response_comment,
        "fit_response_ai_comment": r.fit_response_ai_comment,
        "ai_draft_status": r.ai_draft_status,
        "source": r.source,
        "source_excerpt": r.source_excerpt,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }



def _resolve_org_id(
    db: Session, current_user: User, requested: Optional[str],
) -> str:
    """Pick the organization for a new Opportunity. If the caller only
    belongs to one, use it. If multiple, require an explicit choice."""
    from src.db.models import OrganizationMembership
    rows = (
        db.query(OrganizationMembership.organization_id)
        .filter(OrganizationMembership.user_id == current_user.id)
        .all()
    )
    org_ids = [r[0] for r in rows]
    if not org_ids:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "You are not a member of any organization.",
        )
    if requested:
        if requested not in org_ids:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, "Organization not found",
            )
        return requested
    if len(org_ids) == 1:
        return org_ids[0]
    raise HTTPException(
        status.HTTP_400_BAD_REQUEST,
        "You are a member of multiple organizations; specify one.",
    )



# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------
class CreateOpportunityBody(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    client_name: str = Field(..., min_length=1, max_length=200)
    organization_id: Optional[str] = None



class UpdateOpportunityBody(BaseModel):
    title: Optional[str] = Field(None, max_length=200)
    client_name: Optional[str] = Field(None, max_length=200)



class FinalizeRequirementBody(BaseModel):
    fit_response: str = Field(..., min_length=1, max_length=64)
    comment: Optional[str] = Field(None, max_length=2_000)



class AssignConsultantBody(BaseModel):
    consultant_user_id: str = Field(..., min_length=1, max_length=64)



class MarkWonBody(BaseModel):
    consultant_user_id: Optional[str] = None
    module: Optional[str] = None
    erp_system: Optional[str] = None



# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@router.get("")
def list_opportunities(
    organization_id: Optional[str] = None,
    current_user: User = Depends(require_permission(Permission.OPPORTUNITY_READ)),
    db: Session = Depends(get_db),
):
    from src.db.models import OrganizationMembership
    if organization_id:
        _require_org_membership(db, current_user.id, organization_id)
        org_ids = [organization_id]
    else:
        rows = (
            db.query(OrganizationMembership.organization_id)
            .filter(OrganizationMembership.user_id == current_user.id)
            .all()
        )
        org_ids = [r[0] for r in rows]


    out = []
    for org_id in org_ids:
        for opp in svc.list_for_organization(db, org_id):
            out.append(_serialize_opportunity(opp))
    return {"opportunities": out}



@router.post("")
def create_opportunity(
    body: CreateOpportunityBody,
    current_user: User = Depends(require_permission(Permission.OPPORTUNITY_CREATE)),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org_id(db, current_user, body.organization_id)
    _require_org_membership(db, current_user.id, org_id)
    opp = svc.create_opportunity(
        db,
        organization_id=org_id,
        created_by_user_id=current_user.id,
        title=body.title,
        client_name=body.client_name,
    )
    db.commit()
    return _serialize_opportunity(opp)



@router.get("/{opportunity_id}")
def get_opportunity(
    opportunity_id: str,
    current_user: User = Depends(require_permission(Permission.OPPORTUNITY_READ)),
    db: Session = Depends(get_db),
):
    opp = _load_owned_opportunity(db, opportunity_id, current_user.id)
    return _serialize_opportunity(opp)



@router.patch("/{opportunity_id}")
def update_opportunity(
    opportunity_id: str,
    body: UpdateOpportunityBody,
    current_user: User = Depends(require_permission(Permission.OPPORTUNITY_EDIT)),
    db: Session = Depends(get_db),
):
    opp = _load_owned_opportunity(db, opportunity_id, current_user.id)
    if opp.status in ("won", "lost", "archived"):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Cannot edit an opportunity in status {opp.status!r}.",
        )
    svc.update_opportunity(
        db, opp, title=body.title, client_name=body.client_name,
    )
    db.commit()
    return _serialize_opportunity(opp)



@router.get("/{opportunity_id}/requirements")
def list_requirements(
    opportunity_id: str,
    current_user: User = Depends(require_permission(Permission.OPPORTUNITY_READ)),
    db: Session = Depends(get_db),
):
    _load_owned_opportunity(db, opportunity_id, current_user.id)
    rows = svc.list_requirements(db, opportunity_id)
    return {"requirements": [_serialize_requirement(r) for r in rows]}



@router.get("/{opportunity_id}/eligible-consultants")
def eligible_consultants(
    opportunity_id: str,
    current_user: User = Depends(require_permission(Permission.OPPORTUNITY_EDIT)),
    db: Session = Depends(get_db),
):
    opp = _load_owned_opportunity(db, opportunity_id, current_user.id)
    return {"users": svc.list_eligible_consultants(db, opp.organization_id)}



@router.post("/{opportunity_id}/assign-consultant")
def assign_consultant(
    opportunity_id: str,
    body: AssignConsultantBody,
    current_user: User = Depends(require_permission(Permission.OPPORTUNITY_EDIT)),
    db: Session = Depends(get_db),
):
    opp = _load_owned_opportunity(db, opportunity_id, current_user.id)
    if opp.status in ("won", "lost", "archived"):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Cannot assign a consultant to an opportunity in status {opp.status!r}.",
        )
    try:
        svc.assign_consultant(db, opp, body.consultant_user_id)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    db.commit()
    return _serialize_opportunity(opp)



# ---------------------------------------------------------------------------
# TOR upload and extraction
# ---------------------------------------------------------------------------
_ALLOWED_TOR_SUFFIXES = (".docx", ".doc", ".xlsx", ".xls")



@router.post("/{opportunity_id}/tor")
async def upload_tor(
    opportunity_id: str,
    file: UploadFile = File(...),
    current_user: User = Depends(require_permission(Permission.OPPORTUNITY_UPLOAD_TOR)),
    db: Session = Depends(get_db),
):
    opp = _load_owned_opportunity(db, opportunity_id, current_user.id)
    if opp.status in ("won", "lost", "archived"):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Cannot upload a TOR to an opportunity in status {opp.status!r}.",
        )


    filename = file.filename or "tor"
    if not filename.lower().endswith(_ALLOWED_TOR_SUFFIXES):
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "TOR must be a Word (.docx) or Excel (.xlsx) file.",
        )


    source_format = tor_extraction.detect_format(filename, file.content_type or "")
    if source_format is None:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "Could not determine TOR file type.",
        )


    if not getattr(__import__("src.config.settings", fromlist=["settings"]).settings,
                  "object_storage_configured", False):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Object storage is not configured; TOR upload is unavailable.",
        )


    content = await file.read()
    if not content:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Empty file.")


    # 1) Parse.
    try:
        rows = tor_extraction.extract_tor(content, source_format)
    except tor_extraction.TorExtractionError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))


    # 2) Upload to storage.
    doc_id = uuid.uuid4().hex
    storage_key = object_storage.make_opportunity_storage_key(
        opp.organization_id, opp.id, doc_id, filename,
    )
    try:
        object_storage.upload_bytes(
            storage_key, content, file.content_type or "application/octet-stream",
        )
    except ObjectStorageNotConfigured:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Object storage is not configured.",
        )
    except ObjectStorageError as e:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"Upload to storage failed: {e}",
        )


    # 3) Persist rows + doc.
    try:
        svc.attach_document(
            db,
            opp=opp,
            user_id=current_user.id,
            filename=filename,
            storage_key=storage_key,
            content_type=file.content_type or "application/octet-stream",
            size_bytes=len(content),
            extracted_text_chars=sum(len(r["description"]) for r in rows),
            source_format=source_format,
        )
        added = svc.replace_requirements_from_extraction(
            db, opp=opp, extracted_rows=rows, source_format=source_format,
        )
        db.commit()
    except Exception:
        # Best-effort storage cleanup, then re-raise.
        try:
            object_storage.delete_object(storage_key)
        except Exception:  # noqa: BLE001
            pass
        raise


    return {
        "opportunity_id": opp.id,
        "source_format": source_format,
        "requirements_added": added,
        "requirements": [
            _serialize_requirement(r)
            for r in svc.list_requirements(db, opp.id)
        ],
    }



@router.post("/{opportunity_id}/requirements/{requirement_id}/draft")
def draft_requirement(
    opportunity_id: str,
    requirement_id: str,
    current_user: User = Depends(require_permission(Permission.OPPORTUNITY_EDIT)),
    db: Session = Depends(get_db),
):
    opp = _load_owned_opportunity(db, opportunity_id, current_user.id)
    if opp.status in ("won", "lost", "archived"):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Cannot draft a fit response for an opportunity in status {opp.status!r}.",
        )
    req = svc.get_requirement(db, opportunity_id, requirement_id)
    if req is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Requirement not found")
    if req.ai_draft_status == "finalized":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This requirement is already finalized.",
        )
    try:
        svc.draft_fit_response(db, opp=opp, requirement=req)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"AI draft failed: {e}",
        )
    db.commit()
    return _serialize_requirement(req)



@router.patch("/{opportunity_id}/requirements/{requirement_id}")
def finalize_requirement(
    opportunity_id: str,
    requirement_id: str,
    body: FinalizeRequirementBody,
    current_user: User = Depends(require_permission(Permission.OPPORTUNITY_EDIT)),
    db: Session = Depends(get_db),
):
    opp = _load_owned_opportunity(db, opportunity_id, current_user.id)
    if opp.status in ("won", "lost", "archived"):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Cannot finalize a requirement for an opportunity in status {opp.status!r}.",
        )
    req = svc.get_requirement(db, opportunity_id, requirement_id)
    if req is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Requirement not found")
    try:
        svc.finalize_requirement(
            db, opp=opp, requirement=req,
            fit_response=body.fit_response, comment=body.comment,
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    db.commit()
    return _serialize_requirement(req)



@router.post("/{opportunity_id}/mark-tor-finalized")
def mark_tor_finalized(
    opportunity_id: str,
    current_user: User = Depends(require_permission(Permission.OPPORTUNITY_EDIT)),
    db: Session = Depends(get_db),
):
    opp = _load_owned_opportunity(db, opportunity_id, current_user.id)
    if opp.status in ("won", "lost", "archived"):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Cannot finalize the TOR for an opportunity in status {opp.status!r}.",
        )
    try:
        svc.mark_tor_finalized(db, opp)
    except ValueError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))
    db.commit()
    return _serialize_opportunity(opp)



# ---------------------------------------------------------------------------
# Tender response document
# ---------------------------------------------------------------------------
@router.post("/{opportunity_id}/generate-response")
def generate_response(
    opportunity_id: str,
    current_user: User = Depends(require_permission(Permission.OPPORTUNITY_GENERATE_RESPONSE)),
    db: Session = Depends(get_db),
):
    opp = _load_owned_opportunity(db, opportunity_id, current_user.id)
    if opp.status in ("won", "lost", "archived"):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Cannot generate a response for an opportunity in status {opp.status!r}.",
        )
    requirements = svc.list_requirements(db, opp.id)
    finalized = [r for r in requirements if r.ai_draft_status == "finalized"]
    if not finalized:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "No finalized requirements to include in the response.",
        )


    try:
        filepath = doc_generator.generate_tender_response(
            opportunity_id=opp.id,
            title=opp.title,
            client_name=opp.client_name,
            requirements=[
                {
                    "external_code": r.external_code,
                    "category": r.category,
                    "description": r.description,
                    "priority": r.priority,
                    "req_type": r.req_type,
                    "fit_response": r.fit_response,
                    "fit_response_comment": r.fit_response_comment,
                }
                for r in finalized
            ],
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"Document generation failed: {e}",
        )


    doc = svc.store_tender_response(
        db, opp=opp, filepath=filepath,
        content_type=(
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        ),
    )
    db.commit()
    return {
        "opportunity_id": opp.id,
        "document_id": doc.id,
        "filename": doc.filename,
    }



@router.get("/{opportunity_id}/tender-response/download")
def download_response(
    opportunity_id: str,
    current_user: User = Depends(require_permission(Permission.OPPORTUNITY_READ)),
    db: Session = Depends(get_db),
):
    _load_owned_opportunity(db, opportunity_id, current_user.id)
    doc = svc.current_tender_response(db, opportunity_id)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No response document yet.")
    return Response(
        content=doc.content,
        media_type=doc.content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{doc.filename}"',
        },
    )



# ---------------------------------------------------------------------------
# Mark as Won
# ---------------------------------------------------------------------------
@router.post("/{opportunity_id}/mark-won")
def mark_won(
    opportunity_id: str,
    body: MarkWonBody,
    current_user: User = Depends(require_permission(Permission.OPPORTUNITY_MARK_WON)),
    db: Session = Depends(get_db),
):
    opp = _load_owned_opportunity_locked(db, opportunity_id, current_user.id)


    # Resolve the consultant that will own the eventual session.
    resolved = body.consultant_user_id or opp.assigned_consultant_user_id
    if not resolved:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "A Functional Consultant must be provided or pre-assigned.",
        )


    module = body.module or "FI"
    erp_system = body.erp_system or "SAP S/4HANA"


    try:
        result = svc.mark_won(
            db, opp=opp,
            consultant_user_id=body.consultant_user_id,
            module=module, erp_system=erp_system,
        )
    except ValueError as e:
        msg = str(e)
        if "not found" in msg.lower():
            raise HTTPException(status.HTTP_404_NOT_FOUND, msg)
        if "already" in msg.lower() or "finalize" in msg.lower():
            raise HTTPException(status.HTTP_409_CONFLICT, msg)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, msg)


    # Commit once. Everything rolls back together on any earlier failure.
    db.commit()


    # Post-commit: best-effort email. A send failure does not roll back.
    try:
        from src.db.models import User
        consultant = db.get(User, result["consultant_user_id"])
        if consultant is not None:
            svc.send_bid_won_email(
                to_email=consultant.email,
                consultant_name=consultant.name,
                opportunity_title=opp.title,
                client_name=opp.client_name,
                session_id=result["session_id"],
            )
    except Exception as e:  # noqa: BLE001
        import logging as _logging
        _logging.getLogger(__name__).error(
            "bid-won email dispatch failed opportunity=%s error=%s",
            opp.id, e,
        )


    return {
        "opportunity_id": opp.id,
        "session_id": result["session_id"],
        "consultant_user_id": result["consultant_user_id"],
    }