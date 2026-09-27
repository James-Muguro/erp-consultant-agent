"""Unified attention/routing service.

Single source of truth for the consultant inbox. Every actionable
hand-off across the product routes through this service. There is
deliberately no parallel notification mechanism.

Design notes
------------
  * Source records remain authoritative. This module stores only routing
    state - recipient, source pointer, resolved/pending. It never
    duplicates source-domain data.
  * The service is source-agnostic. It knows the three source types by
    string, not by importing the modules that produce them. This avoids
    import cycles and keeps the service small.
  * Display adapters (which turn a source pointer into a user-facing
    title/URL) are registered by the feature modules that own the source.
    If no adapter is registered for a source_type, the API layer returns
    a stub display rather than failing. This makes it safe to land the
    shared infrastructure before the sources.
  * Every method takes an explicit `db: Session`. The service never
    commits; callers own the transaction.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from src.db.models import AttentionItem


SOURCE_TYPE_ERP_USER_REQUEST = "erp_user_request"
SOURCE_TYPE_DEVELOPER_COMPLETION_ISSUE = "developer_completion_issue"
SOURCE_TYPE_DEVELOPER_COMPLETION_TEST_CASE = "developer_completion_test_case"
SOURCE_TYPE_BID_WON = "bid_won"

KNOWN_SOURCE_TYPES = frozenset({
    SOURCE_TYPE_ERP_USER_REQUEST,
    SOURCE_TYPE_DEVELOPER_COMPLETION_ISSUE,
    SOURCE_TYPE_DEVELOPER_COMPLETION_TEST_CASE,
    SOURCE_TYPE_BID_WON,
})

STATUS_PENDING = "pending"
STATUS_RESOLVED = "resolved"


# ---------------------------------------------------------------------------
# Adapter registry
# ---------------------------------------------------------------------------
# A source adapter takes a db session and an AttentionItem, and returns
# a display dict with keys {title, subtitle, context_url}. Returning
# None signals "source record not found" and triggers the stub fallback
# in the API layer.
AttentionSourceAdapter = Callable[
    [Session, AttentionItem], Optional[Dict[str, Any]],
]

_adapters: Dict[str, AttentionSourceAdapter] = {}


def register_source_adapter(
    source_type: str, adapter: AttentionSourceAdapter,
) -> None:
    """Register a display adapter for a source type.

    Called at import time by the feature module that owns the source.
    Registering twice for the same source_type replaces the prior
    adapter; the last write wins. Feature modules are imported exactly
    once at process start, so this is deterministic.
    """
    if source_type not in KNOWN_SOURCE_TYPES:
        raise ValueError(f"Unknown attention source_type: {source_type!r}")
    _adapters[source_type] = adapter


def get_source_adapter(
    source_type: str,
) -> Optional[AttentionSourceAdapter]:
    return _adapters.get(source_type)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _validate_source_type(source_type: str) -> None:
    if source_type not in KNOWN_SOURCE_TYPES:
        raise ValueError(f"Unknown attention source_type: {source_type!r}")


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------
def create_attention_item(
    db: Session,
    *,
    recipient_user_id: str,
    source_type: str,
    source_id: str,
    organization_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> AttentionItem:
    """Create (or return the existing) pending item for this tuple.

    Idempotent: if a pending item already exists for the same
    (source_type, source_id, recipient_user_id), it is returned as-is.
    This makes retries safe (e.g. a caller re-invoked after a partial
    upstream failure).

    Does not commit. The caller owns the transaction, because the item
    is almost always created alongside a state transition on the source.
    """
    _validate_source_type(source_type)

    existing = (
        db.query(AttentionItem)
        .filter(
            AttentionItem.source_type == source_type,
            AttentionItem.source_id == source_id,
            AttentionItem.recipient_user_id == recipient_user_id,
            AttentionItem.status == STATUS_PENDING,
        )
        .first()
    )
    if existing is not None:
        return existing

    item = AttentionItem(
        id=uuid.uuid4().hex,
        recipient_user_id=recipient_user_id,
        organization_id=organization_id,
        session_id=session_id,
        source_type=source_type,
        source_id=source_id,
        status=STATUS_PENDING,
        created_at=_utcnow(),
    )
    db.add(item)
    db.flush()
    return item


def resolve_attention_item(
    db: Session, item_id: str, resolved_by_user_id: str,
) -> bool:
    """Mark one item resolved. Returns False if the item does not exist
    or is already resolved. Does not commit."""
    item = db.get(AttentionItem, item_id)
    if item is None or item.status != STATUS_PENDING:
        return False
    item.status = STATUS_RESOLVED
    item.resolved_at = _utcnow()
    item.resolved_by_user_id = resolved_by_user_id
    return True


def resolve_for_source(
    db: Session, source_type: str, source_id: str,
) -> int:
    """Resolve every pending item for a source, regardless of recipient.

    Used when the source workflow reaches its terminal state and every
    routed copy of the item should close in one operation (e.g. an ERP
    User request resolved by one consultant must disappear from every
    other consultant's inbox).

    Returns the number of items resolved. Does not commit.
    """
    _validate_source_type(source_type)

    now = _utcnow()
    rows = (
        db.query(AttentionItem)
        .filter(
            AttentionItem.source_type == source_type,
            AttentionItem.source_id == source_id,
            AttentionItem.status == STATUS_PENDING,
        )
        .all()
    )
    for item in rows:
        item.status = STATUS_RESOLVED
        item.resolved_at = now
    return len(rows)


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------
def list_pending(
    db: Session, recipient_user_id: str,
) -> List[AttentionItem]:
    return (
        db.query(AttentionItem)
        .filter(
            AttentionItem.recipient_user_id == recipient_user_id,
            AttentionItem.status == STATUS_PENDING,
        )
        .order_by(AttentionItem.created_at.desc())
        .all()
    )


def list_history(
    db: Session, recipient_user_id: str, limit: int = 100,
) -> List[AttentionItem]:
    return (
        db.query(AttentionItem)
        .filter(
            AttentionItem.recipient_user_id == recipient_user_id,
            AttentionItem.status != STATUS_PENDING,
        )
        .order_by(AttentionItem.resolved_at.desc())
        .limit(limit)
        .all()
    )


def count_pending(db: Session, recipient_user_id: str) -> int:
    return (
        db.query(AttentionItem)
        .filter(
            AttentionItem.recipient_user_id == recipient_user_id,
            AttentionItem.status == STATUS_PENDING,
        )
        .count()
    )


def get_item(
    db: Session, item_id: str,
) -> Optional[AttentionItem]:
    return db.get(AttentionItem, item_id)


# ---------------------------------------------------------------------------
# Recipient resolution
# ---------------------------------------------------------------------------
def resolve_recipients_for_session(db: Session, session) -> List[str]:
    """Which users should receive attention items for a workflow event on
    this project.

    Policy (locked):
      * Organization-owned project: every member of the owning
        organization who holds the functional_consultant role. No second
        consultant directory.
      * Personal project: the project owner, if any. Personal projects
        have no organization, so there are no FC members to route to.

    Shared by the ERP User request flow and the developer-completion
    flow so the two cannot drift.
    """
    from src.db.models import (
        OrganizationMembership,
        UserRoleRecord,
    )

    if getattr(session, "organization_id", None) is None:
        owner = getattr(session, "user_id", None)
        return [owner] if owner else []

    rows = (
        db.query(UserRoleRecord.user_id)
        .join(
            OrganizationMembership,
            OrganizationMembership.user_id == UserRoleRecord.user_id,
        )
        .filter(
            OrganizationMembership.organization_id == session.organization_id,
            UserRoleRecord.role == "functional_consultant",
        )
        .all()
    )
    seen: set = set()
    out: List[str] = []
    for (user_id,) in rows:
        if user_id in seen:
            continue
        seen.add(user_id)
        out.append(user_id)
    return out