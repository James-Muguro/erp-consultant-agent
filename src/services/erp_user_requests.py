"""ERP User request service - the workflow-item side of ERP User input.

Distinct from SessionStakeholderSubmission (Phase 2.4), which is
evidence captured from the questionnaire. Requests have a status, a
resolver, and a corresponding attention_items row per recipient
consultant.

Recipient selection is intentional and locked:
  * Organization-owned project: every member of the owning organization
    who holds the functional_consultant role. No second consultant
    directory.
  * Personal project: the project owner, if any. Personal projects have
    no organization, so there are no FC members to route to.

Every recipient gets their own attention_items row. Resolving the
request from any one of them closes the pending items for all of them
(resolve_for_source is called from the resolve flow).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from src.db.models import (
    ErpUserRequest,
    OrganizationMembership,
    SessionRecord,
    UserRoleRecord,
)
from src.services import attention_service


REQUEST_TYPE_CHANGE = "change"
REQUEST_TYPE_QUESTION = "question"
REQUEST_TYPE_ISSUE = "issue"
REQUEST_TYPE_OTHER = "other"

KNOWN_REQUEST_TYPES = frozenset({
    REQUEST_TYPE_CHANGE,
    REQUEST_TYPE_QUESTION,
    REQUEST_TYPE_ISSUE,
    REQUEST_TYPE_OTHER,
})


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _resolve_request_recipients(
    db: Session, session: SessionRecord,
) -> List[str]:
    """See attention_service.resolve_recipients_for_session for the
    policy. This wrapper exists only for readability at the call site."""
    return attention_service.resolve_recipients_for_session(db, session)


def create_request(
    db: Session,
    *,
    session: SessionRecord,
    created_by_user_id: str,
    request_type: str,
    subject: str,
    body: str,
) -> ErpUserRequest:
    """Create a request and route it to every eligible consultant.

    One transaction with the caller. Creates the request row and one
    attention_items row per recipient. Does not commit.
    """
    if request_type not in KNOWN_REQUEST_TYPES:
        raise ValueError(f"Unknown request_type: {request_type!r}")

    request = ErpUserRequest(
        id=uuid.uuid4().hex,
        session_id=session.session_id,
        created_by_user_id=created_by_user_id,
        request_type=request_type,
        subject=subject,
        body=body,
        status="open",
        created_at=_utcnow(),
        updated_at=_utcnow(),
    )
    db.add(request)
    db.flush()

    recipients = _resolve_request_recipients(db, session)
    for recipient_id in recipients:
        attention_service.create_attention_item(
            db,
            recipient_user_id=recipient_id,
            source_type=attention_service.SOURCE_TYPE_ERP_USER_REQUEST,
            source_id=request.id,
            organization_id=session.organization_id,
            session_id=session.session_id,
        )

    return request


def resolve_request(
    db: Session,
    *,
    request: ErpUserRequest,
    resolved_by_user_id: str,
) -> bool:
    """Mark the request resolved and close every pending attention item
    for it across every recipient. Returns False if already resolved."""
    if request.status != "open":
        return False
    request.status = "resolved"
    request.resolved_at = _utcnow()
    request.resolved_by_user_id = resolved_by_user_id
    request.updated_at = _utcnow()

    attention_service.resolve_for_source(
        db,
        source_type=attention_service.SOURCE_TYPE_ERP_USER_REQUEST,
        source_id=request.id,
    )
    return True


def list_for_project(
    db: Session, session_id: str, status: Optional[str] = None,
) -> List[ErpUserRequest]:
    q = db.query(ErpUserRequest).filter(
        ErpUserRequest.session_id == session_id,
    )
    if status:
        q = q.filter(ErpUserRequest.status == status)
    return q.order_by(ErpUserRequest.created_at.desc()).all()


def list_for_user(
    db: Session, session_id: str, user_id: str,
) -> List[ErpUserRequest]:
    return (
        db.query(ErpUserRequest)
        .filter(
            ErpUserRequest.session_id == session_id,
            ErpUserRequest.created_by_user_id == user_id,
        )
        .order_by(ErpUserRequest.created_at.desc())
        .all()
    )


def get_request(
    db: Session, request_id: str, session_id: str,
) -> Optional[ErpUserRequest]:
    row = db.get(ErpUserRequest, request_id)
    if row is None or row.session_id != session_id:
        return None
    return row


# ---------------------------------------------------------------------------
# Display adapter for the unified inbox
# ---------------------------------------------------------------------------
def _adapter(db: Session, item) -> Optional[Dict[str, Any]]:
    request = db.get(ErpUserRequest, item.source_id)
    if request is None:
        return None
    return {
        "title": request.subject,
        "subtitle": f"{request.request_type} · {request.status}",
        "context_url": (
            f"/p/{request.session_id}/support"
            f"?focus=erp-user-request:{request.id}"
        ),
    }

attention_service.register_source_adapter(
    attention_service.SOURCE_TYPE_ERP_USER_REQUEST, _adapter,
)