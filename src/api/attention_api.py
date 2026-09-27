"""Unified consultant inbox endpoints.

Every route requires INBOX_READ (Functional Consultant only) and reads
only the caller's own items. Cross-recipient access is not possible by
construction: every query is filtered on `recipient_user_id == current_user.id`.

The inbox never performs a source state transition. Opening an item
routes to the source workflow, which owns its own state machine. The
optional resolve endpoint on this router only closes the attention item;
callers reach it deliberately (e.g. a "dismiss" action) and it does not
touch the source record.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from src.auth.dependencies import get_db
from src.auth.guards import require_permission
from src.auth.permissions import Permission
from src.db.models import AttentionItem, User
from src.services import attention_service


logger = logging.getLogger(__name__)


router = APIRouter(prefix="/api/inbox", tags=["inbox"])


def _expand(db: Session, item: AttentionItem) -> Dict[str, Any]:
    """Return the wire representation of one attention item, with its
    source-domain display fields resolved via the registered adapter.

    Adapter failures are logged and degrade to a stub, never propagated:
    one broken source must not break the whole inbox.
    """
    display: Dict[str, Any] | None = None
    adapter = attention_service.get_source_adapter(item.source_type)
    if adapter is not None:
        try:
            display = adapter(db, item)
        except Exception as e:  # noqa: BLE001 - adapter must never break the inbox
            logger.warning(
                "Attention source adapter failed source_type=%s source_id=%s error=%s",
                item.source_type, item.source_id, e,
            )
            display = None

    if display is None:
        display = {
            "title": item.source_type.replace("_", " ").title(),
            "subtitle": None,
            "context_url": None,
        }

    return {
        "id": item.id,
        "source_type": item.source_type,
        "source_id": item.source_id,
        "session_id": item.session_id,
        "organization_id": item.organization_id,
        "status": item.status,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "resolved_at": item.resolved_at.isoformat() if item.resolved_at else None,
        "resolved_by_user_id": item.resolved_by_user_id,
        "title": display.get("title"),
        "subtitle": display.get("subtitle"),
        "context_url": display.get("context_url"),
    }


@router.get("")
def list_inbox(
    current_user: User = Depends(require_permission(Permission.INBOX_READ)),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    items = attention_service.list_pending(db, current_user.id)
    return {"items": [_expand(db, item) for item in items]}


@router.get("/history")
def list_inbox_history(
    current_user: User = Depends(require_permission(Permission.INBOX_READ)),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    items = attention_service.list_history(db, current_user.id)
    return {"items": [_expand(db, item) for item in items]}


@router.get("/count")
def inbox_count(
    current_user: User = Depends(require_permission(Permission.INBOX_READ)),
    db: Session = Depends(get_db),
) -> Dict[str, int]:
    return {"pending": attention_service.count_pending(db, current_user.id)}


@router.post("/{item_id}/resolve")
def resolve_item(
    item_id: str,
    current_user: User = Depends(require_permission(Permission.INBOX_READ)),
    db: Session = Depends(get_db),
) -> Dict[str, bool]:
    item = attention_service.get_item(db, item_id)
    if (
        item is None
        or item.recipient_user_id != current_user.id
        or item.status != attention_service.STATUS_PENDING
    ):
        # 404 for every failure mode: unknown id, wrong recipient,
        # already resolved. The caller must not be able to distinguish
        # "no such item" from "not yours".
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Inbox item not found")

    ok = attention_service.resolve_attention_item(
        db, item_id, current_user.id,
    )
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Inbox item not found")
    db.commit()
    return {"resolved": True}