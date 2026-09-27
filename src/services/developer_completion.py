"""Attention source adapters for developer completion items.

Registered at import time so the unified inbox can render an issue or a
test case routed for consultant review. Kept separate from
project_intelligence to avoid a cycle: project_intelligence performs the
state transitions and fan-out; this module only supplies display data.

Each adapter includes the developer who marked the item complete, so the
consultant reviewing the inbox sees attribution without having to open
the source workflow first.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from src.db.models import ProjectIssue, TestCaseRecord, User
from src.services import attention_service


def _user_display(db: Session, user_id: Optional[str]) -> Optional[str]:
    if not user_id:
        return None
    user = db.get(User, user_id)
    if user is None:
        return None
    return user.name or user.email


def _issue_adapter(db: Session, item) -> Optional[Dict[str, Any]]:
    issue = db.get(ProjectIssue, item.source_id)
    if issue is None:
        return None

    subtitle_bits = [
        issue.issue_type,
        f"severity {issue.severity}",
    ]
    completed_by = _user_display(
        db, getattr(issue, "last_completed_by_user_id", None),
    )
    if completed_by:
        subtitle_bits.append(f"completed by {completed_by}")

    return {
        "title": f"Issue: {issue.description[:80]}",
        "subtitle": " · ".join(subtitle_bits),
        "context_url": (
            f"/p/{issue.session_id}/issues?focus=issue:{issue.id}"
        ),
    }


def _test_case_adapter(db: Session, item) -> Optional[Dict[str, Any]]:
    tc = db.get(TestCaseRecord, item.source_id)
    if tc is None:
        return None

    external = f"{tc.external_code} " if tc.external_code else ""
    subtitle_bits = [tc.test_type, f"priority {tc.priority}"]
    completed_by = _user_display(
        db, getattr(tc, "last_completed_by_user_id", None),
    )
    if completed_by:
        subtitle_bits.append(f"completed by {completed_by}")

    return {
        "title": f"Test case: {external}{tc.scenario[:80]}",
        "subtitle": " · ".join(subtitle_bits),
        "context_url": (
            f"/p/{tc.session_id}/testing?focus=test_case:{tc.id}"
        ),
    }


attention_service.register_source_adapter(
    attention_service.SOURCE_TYPE_DEVELOPER_COMPLETION_ISSUE,
    _issue_adapter,
)
attention_service.register_source_adapter(
    attention_service.SOURCE_TYPE_DEVELOPER_COMPLETION_TEST_CASE,
    _test_case_adapter,
)