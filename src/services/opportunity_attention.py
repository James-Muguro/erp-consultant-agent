"""Attention source adapter for bid-won hand-offs.

Registered at import time. Resolves an Opportunity into a display row
for the unified inbox.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from src.db.models import Opportunity
from src.services import attention_service


def _bid_won_adapter(db: Session, item) -> Optional[Dict[str, Any]]:
    opp = db.get(Opportunity, item.source_id)
    if opp is None:
        return None
    # The recipient is a Functional Consultant, who does not hold
    # `opportunity:read`. If the session is missing (defensive - it is
    # set in the same transaction that creates the item), do not send
    # the caller to a Business Development-only route; render the row
    # non-clickable instead.
    return {
        "title": f"New project: {opp.title}",
        "subtitle": f"Client: {opp.client_name}",
        "context_url": (
            f"/p/{item.session_id}" if item.session_id else None
        ),
    }


attention_service.register_source_adapter(
    attention_service.SOURCE_TYPE_BID_WON, _bid_won_adapter,
)