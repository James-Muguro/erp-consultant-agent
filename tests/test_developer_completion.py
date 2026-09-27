"""
Integration tests for the developer ↔ consultant completion workflow.

Scope:
  * Issue state machine: open → developer_marked_complete → (confirm |
    reopen). Reopened items accept a second developer-complete.
  * Test-case state machine: same four states, exercising the four
    Phase 2.8 columns on TestCaseRecord at runtime.
  * Invalid-transition matrix (both entities): confirm / reopen /
    developer-complete from every state that is not their allowed source.
  * Reopen note validation (both entities).
  * ReviewAction audit trail: one row per transition, correct action
    strings, reopen note persisted.
  * Attention integration: developer-complete fans out one pending item
    per recipient; confirm and reopen both resolve the pending item;
    reopen never creates a new attention item (Phase 2.5 Q6 rule).
  * Adapter presentation: title / subtitle / context_url for both
    developer-completion adapters.
  * Authorization: unauthenticated 401, wrong-capability 403, cross-user
    404 (both across sessions and within a session).

Fixtures from tests/conftest.py:
    * client            TestClient(app) with lifespan.
    * auth_headers      fresh functional_consultant (holds ISSUES_WRITE,
                        TESTING_WRITE, REVIEWS_SUBMIT, PROJECT_CREATE).
    * cleanup_registry  tracks users, orgs, opportunities for teardown.
    * unique_email      unique-address helper.

Direct database setup:
    There is no HTTP endpoint for creating an arbitrary ProjectIssue or
    TestCaseRecord. Issues are created via project_intelligence.create_issue;
    test cases via project_intelligence.sync_test_cases_from_structured.
    Organizations and memberships are inserted directly because there is
    no HTTP path for adding a membership to an existing user. All created
    users, organizations, and opportunities are registered with
    cleanup_registry.

PostgreSQL only. No SQLite branches, no DATABASE_URL override, no
transaction-rollback isolation.
"""
from __future__ import annotations

import uuid
from typing import Dict

import pytest

from src.db.base import SessionLocal
from src.db.models import (
    Organization,
    OrganizationMembership,
    ReviewAction,
)
from src.services import attention_service
from src.services import project_intelligence
from tests._auth_helpers import signup_and_authenticate
from tests.conftest import unique_email


# ---------------------------------------------------------------------------
# Local helpers
# ---------------------------------------------------------------------------
def _user_id(client, headers: Dict[str, str]) -> str:
    r = client.get("/api/auth/me", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _user_email(client, headers: Dict[str, str]) -> str:
    r = client.get("/api/auth/me", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["email"]


def _signup_with_role(client, cleanup_registry, role: str) -> Dict[str, str]:
    email = unique_email(f"dc-{role}")
    cleanup_registry.emails.append(email)
    token = signup_and_authenticate(client, email=email, account_type=role)
    return {"Authorization": f"Bearer {token}"}


def _create_project(client, headers, name: str, organization_id=None) -> str:
    payload = {"project_name": name, "module": "FI"}
    if organization_id is not None:
        payload["organization_id"] = organization_id
    r = client.post("/api/projects/start", json=payload, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["session_id"]


def _create_issue(sid: str, description: str = "Test issue") -> str:
    return project_intelligence.create_issue(
        sid, "test_failure", description, severity="medium",
    )


def _create_test_case(
    sid: str, code: str = "TC-001", scenario: str = "Test scenario",
) -> str:
    ids = project_intelligence.sync_test_cases_from_structured(
        sid, "QA", [{"id": code, "scenario": scenario}],
    )
    assert ids, "sync_test_cases_from_structured returned no ids"
    return ids[0]


def _insert_org_with_owner(db, user_id: str, name: str) -> str:
    org_id = uuid.uuid4().hex
    db.add(Organization(id=org_id, name=name, created_by=user_id))
    db.add(OrganizationMembership(
        id=uuid.uuid4().hex,
        organization_id=org_id,
        user_id=user_id,
        role="owner",
    ))
    db.commit()
    return org_id


def _insert_membership(db, user_id: str, org_id: str, role: str) -> None:
    db.add(OrganizationMembership(
        id=uuid.uuid4().hex,
        organization_id=org_id,
        user_id=user_id,
        role=role,
    ))
    db.commit()


def _drive_issue_to(sid: str, issue_id: str, user_id: str, target: str) -> None:
    """Bring an issue to the requested state via the public service
    functions. Called only for the invalid-transition matrix."""
    if target == "open":
        return
    if target == "developer_marked_complete":
        project_intelligence.mark_issue_developer_complete(sid, issue_id, user_id)
        return
    if target == "reopened_with_feedback":
        project_intelligence.mark_issue_developer_complete(sid, issue_id, user_id)
        project_intelligence.reopen_issue(sid, issue_id, user_id, "Feedback")
        return
    if target == "consultant_confirmed_resolved":
        project_intelligence.mark_issue_developer_complete(sid, issue_id, user_id)
        project_intelligence.confirm_issue_resolved(sid, issue_id, user_id)
        return
    raise ValueError(f"Unknown target state: {target}")


def _drive_test_case_to(sid: str, tc_id: str, user_id: str, target: str) -> None:
    if target == "open":
        return
    if target == "developer_marked_complete":
        project_intelligence.mark_test_case_developer_complete(sid, tc_id, user_id)
        return
    if target == "reopened_with_feedback":
        project_intelligence.mark_test_case_developer_complete(sid, tc_id, user_id)
        project_intelligence.reopen_test_case(sid, tc_id, user_id, "Feedback")
        return
    if target == "consultant_confirmed_resolved":
        project_intelligence.mark_test_case_developer_complete(sid, tc_id, user_id)
        project_intelligence.confirm_test_case_resolved(sid, tc_id, user_id)
        return
    raise ValueError(f"Unknown target state: {target}")


def _review_actions(db, sid: str, object_type: str, object_id: str):
    return (
        db.query(ReviewAction)
        .filter(
            ReviewAction.session_id == sid,
            ReviewAction.object_type == object_type,
            ReviewAction.object_id == object_id,
        )
        .order_by(ReviewAction.created_at)
        .all()
    )


@pytest.fixture
def db():
    """A SessionLocal for direct setup and inspection. The application
    opens its own session per HTTP request; both target the same
    PostgreSQL database, so commits here are immediately visible to the
    running app and vice versa."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Issues — state machine
# ---------------------------------------------------------------------------
class TestIssueStateMachine:
    def test_issue_full_reopen_cycle_creates_four_review_actions(
        self, client, auth_headers, db,
    ):
        user_id = _user_id(client, auth_headers)
        sid = _create_project(client, auth_headers, "DC Issue Cycle")
        issue_id = _create_issue(sid, "Round trip")

        r = client.post(
            f"/api/projects/{sid}/issues/{issue_id}/developer-complete",
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text

        r = client.post(
            f"/api/projects/{sid}/issues/{issue_id}/reopen",
            json={"note": "Still broken in production"},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text

        r = client.post(
            f"/api/projects/{sid}/issues/{issue_id}/developer-complete",
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text

        r = client.post(
            f"/api/projects/{sid}/issues/{issue_id}/confirm",
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text

        db.expire_all()
        actions = _review_actions(db, sid, "issue", issue_id)
        assert len(actions) == 4
        assert [a.action for a in actions] == [
            "developer_marked_complete",
            "consultant_reopened",
            "developer_marked_complete",
            "consultant_confirmed_resolved",
        ]
        assert actions[0].note is None
        assert actions[1].note == "Still broken in production"
        assert actions[2].note is None
        assert actions[3].note is None
        assert all(a.user_id == user_id for a in actions)

    def test_issue_completion_attribution_and_counter(
        self, client, auth_headers,
    ):
        user_id = _user_id(client, auth_headers)
        sid = _create_project(client, auth_headers, "DC Attribution")
        issue_id = _create_issue(sid)

        r = client.post(
            f"/api/projects/{sid}/issues/{issue_id}/developer-complete",
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text

        issues = project_intelligence.get_issues(sid, status=None)
        row = next(i for i in issues if i["id"] == issue_id)
        assert row["status"] == "developer_marked_complete"
        assert row["completion_count"] == 1
        assert row["last_completed_by_user_id"] == user_id
        assert row["last_completed_at"] is not None

    def test_reopened_issue_listing_exposes_latest_note(
        self, client, auth_headers,
    ):
        user_id = _user_id(client, auth_headers)
        sid = _create_project(client, auth_headers, "DC Reopen Note")
        issue_id = _create_issue(sid)

        client.post(
            f"/api/projects/{sid}/issues/{issue_id}/developer-complete",
            headers=auth_headers,
        )
        r = client.post(
            f"/api/projects/{sid}/issues/{issue_id}/reopen",
            json={"note": "Please add a regression test"},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text

        r = client.get(
            f"/api/projects/{sid}/issues?status=reopened_with_feedback",
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        rows = r.json()["issues"]
        assert len(rows) == 1
        row = rows[0]
        assert row["id"] == issue_id
        assert row["reopen_note"] == "Please add a regression test"
        assert row["reopen_at"] is not None
        assert row["reopen_by_user_id"] == user_id

    @pytest.mark.parametrize(
        "starting_state,action,endpoint_suffix",
        [
            ("open", "confirm", "confirm"),
            ("reopened_with_feedback", "confirm", "confirm"),
            ("open", "reopen", "reopen"),
            ("reopened_with_feedback", "reopen", "reopen"),
            ("developer_marked_complete", "developer-complete", "developer-complete"),
            ("consultant_confirmed_resolved", "developer-complete", "developer-complete"),
        ],
    )
    def test_issue_invalid_transitions(
        self, client, auth_headers,
        starting_state, action, endpoint_suffix,
    ):
        user_id = _user_id(client, auth_headers)
        sid = _create_project(
            client, auth_headers, f"DC Invalid {starting_state} {action}",
        )
        issue_id = _create_issue(sid)
        _drive_issue_to(sid, issue_id, user_id, starting_state)

        body = {"note": "irrelevant"} if endpoint_suffix == "reopen" else None
        r = client.post(
            f"/api/projects/{sid}/issues/{issue_id}/{endpoint_suffix}",
            json=body,
            headers=auth_headers,
        )
        assert r.status_code == 409, (
            f"state={starting_state} action={action} got {r.status_code}: {r.text}"
        )

    def test_issue_reopen_requires_non_empty_note(
        self, client, auth_headers,
    ):
        user_id = _user_id(client, auth_headers)
        sid = _create_project(client, auth_headers, "DC Empty Note")
        issue_id = _create_issue(sid)
        _drive_issue_to(sid, issue_id, user_id, "developer_marked_complete")

        r = client.post(
            f"/api/projects/{sid}/issues/{issue_id}/reopen",
            json={"note": ""},
            headers=auth_headers,
        )
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# Test cases — state machine
# ---------------------------------------------------------------------------
class TestTestCaseStateMachine:
    def test_test_case_full_reopen_cycle_creates_four_review_actions(
        self, client, auth_headers, db,
    ):
        user_id = _user_id(client, auth_headers)
        sid = _create_project(client, auth_headers, "DC TC Cycle")
        tc_id = _create_test_case(sid, "TC-001", "Round trip TC")

        r = client.post(
            f"/api/projects/{sid}/test-cases/{tc_id}/developer-complete",
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text

        r = client.post(
            f"/api/projects/{sid}/test-cases/{tc_id}/reopen",
            json={"note": "Add assertion on response body"},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text

        r = client.post(
            f"/api/projects/{sid}/test-cases/{tc_id}/developer-complete",
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text

        r = client.post(
            f"/api/projects/{sid}/test-cases/{tc_id}/confirm",
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text

        db.expire_all()
        actions = _review_actions(db, sid, "test_case", tc_id)
        assert len(actions) == 4
        assert [a.action for a in actions] == [
            "developer_marked_complete",
            "consultant_reopened",
            "developer_marked_complete",
            "consultant_confirmed_resolved",
        ]
        assert actions[1].note == "Add assertion on response body"
        assert all(a.user_id == user_id for a in actions)

    def test_test_case_completion_persistence_columns(
        self, client, auth_headers,
    ):
        """Regression check for the four Phase 2.8 columns on
        TestCaseRecord: status, completion_count, last_completed_at,
        last_completed_by_user_id."""
        user_id = _user_id(client, auth_headers)
        sid = _create_project(client, auth_headers, "DC TC Persistence")
        tc_id = _create_test_case(sid, "TC-002", "Persistence check")

        r = client.post(
            f"/api/projects/{sid}/test-cases/{tc_id}/developer-complete",
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text

        rows = project_intelligence.get_test_cases(sid)
        row = next(t for t in rows if t["id"] == tc_id)
        assert row["status"] == "developer_marked_complete"
        assert row["completion_count"] == 1
        assert row["last_completed_by_user_id"] == user_id
        assert row["last_completed_at"] is not None

    def test_reopened_test_case_listing_exposes_latest_note(
        self, client, auth_headers,
    ):
        user_id = _user_id(client, auth_headers)
        sid = _create_project(client, auth_headers, "DC TC Reopen")
        tc_id = _create_test_case(sid, "TC-003", "Reopen check")

        client.post(
            f"/api/projects/{sid}/test-cases/{tc_id}/developer-complete",
            headers=auth_headers,
        )
        r = client.post(
            f"/api/projects/{sid}/test-cases/{tc_id}/reopen",
            json={"note": "Cover the negative path"},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text

        r = client.get(
            f"/api/projects/{sid}/test-cases?status=reopened_with_feedback",
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        rows = r.json()["test_cases"]
        assert len(rows) == 1
        row = rows[0]
        assert row["id"] == tc_id
        assert row["reopen_note"] == "Cover the negative path"
        assert row["reopen_at"] is not None
        assert row["reopen_by_user_id"] == user_id

    @pytest.mark.parametrize(
        "starting_state,action,endpoint_suffix",
        [
            ("open", "confirm", "confirm"),
            ("reopened_with_feedback", "confirm", "confirm"),
            ("open", "reopen", "reopen"),
            ("reopened_with_feedback", "reopen", "reopen"),
            ("developer_marked_complete", "developer-complete", "developer-complete"),
            ("consultant_confirmed_resolved", "developer-complete", "developer-complete"),
        ],
    )
    def test_test_case_invalid_transitions(
        self, client, auth_headers,
        starting_state, action, endpoint_suffix,
    ):
        user_id = _user_id(client, auth_headers)
        sid = _create_project(
            client, auth_headers, f"DC TC Invalid {starting_state} {action}",
        )
        tc_id = _create_test_case(sid)
        _drive_test_case_to(sid, tc_id, user_id, starting_state)

        body = {"note": "irrelevant"} if endpoint_suffix == "reopen" else None
        r = client.post(
            f"/api/projects/{sid}/test-cases/{tc_id}/{endpoint_suffix}",
            json=body,
            headers=auth_headers,
        )
        assert r.status_code == 409, (
            f"state={starting_state} action={action} got {r.status_code}: {r.text}"
        )

    def test_test_case_reopen_requires_non_empty_note(
        self, client, auth_headers,
    ):
        user_id = _user_id(client, auth_headers)
        sid = _create_project(client, auth_headers, "DC TC Empty Note")
        tc_id = _create_test_case(sid)
        _drive_test_case_to(sid, tc_id, user_id, "developer_marked_complete")

        r = client.post(
            f"/api/projects/{sid}/test-cases/{tc_id}/reopen",
            json={"note": ""},
            headers=auth_headers,
        )
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# Attention integration
# ---------------------------------------------------------------------------
class TestAttentionIntegration:
    def test_developer_complete_creates_pending_attention_item(
        self, client, auth_headers, db,
    ):
        user_id = _user_id(client, auth_headers)
        sid = _create_project(client, auth_headers, "DC Attention Create")
        issue_id = _create_issue(sid)

        assert attention_service.count_pending(db, user_id) == 0

        r = client.post(
            f"/api/projects/{sid}/issues/{issue_id}/developer-complete",
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text

        db.expire_all()
        assert attention_service.count_pending(db, user_id) == 1
        pending = attention_service.list_pending(db, user_id)
        assert pending[0].source_type == (
            attention_service.SOURCE_TYPE_DEVELOPER_COMPLETION_ISSUE
        )
        assert pending[0].source_id == issue_id
        assert pending[0].session_id == sid

    def test_confirm_resolves_pending_attention_item(
        self, client, auth_headers, db,
    ):
        user_id = _user_id(client, auth_headers)
        sid = _create_project(client, auth_headers, "DC Attention Confirm")
        issue_id = _create_issue(sid)

        client.post(
            f"/api/projects/{sid}/issues/{issue_id}/developer-complete",
            headers=auth_headers,
        )
        db.expire_all()
        assert attention_service.count_pending(db, user_id) == 1

        r = client.post(
            f"/api/projects/{sid}/issues/{issue_id}/confirm",
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text

        db.expire_all()
        assert attention_service.count_pending(db, user_id) == 0
        history = attention_service.list_history(db, user_id)
        source_matches = [
            h for h in history
            if h.source_type
            == attention_service.SOURCE_TYPE_DEVELOPER_COMPLETION_ISSUE
            and h.source_id == issue_id
        ]
        assert len(source_matches) == 1
        assert source_matches[0].status == attention_service.STATUS_RESOLVED

    def test_reopen_resolves_attention_without_creating_new_item(
        self, client, auth_headers, db,
    ):
        """Phase 2.5 Q6: reopen must not produce a developer-facing
        attention item. The pending consultant item is resolved; no new
        item is created."""
        user_id = _user_id(client, auth_headers)
        sid = _create_project(client, auth_headers, "DC Attention Reopen")
        issue_id = _create_issue(sid)

        client.post(
            f"/api/projects/{sid}/issues/{issue_id}/developer-complete",
            headers=auth_headers,
        )
        db.expire_all()
        assert attention_service.count_pending(db, user_id) == 1

        r = client.post(
            f"/api/projects/{sid}/issues/{issue_id}/reopen",
            json={"note": "Back to you"},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text

        db.expire_all()
        assert attention_service.count_pending(db, user_id) == 0

    def test_second_completion_after_reopen_creates_new_pending_item(
        self, client, auth_headers, db,
    ):
        user_id = _user_id(client, auth_headers)
        sid = _create_project(client, auth_headers, "DC Attention Second")
        issue_id = _create_issue(sid)

        client.post(
            f"/api/projects/{sid}/issues/{issue_id}/developer-complete",
            headers=auth_headers,
        )
        db.expire_all()
        first_pending = attention_service.list_pending(db, user_id)
        assert len(first_pending) == 1
        first_item_id = first_pending[0].id

        client.post(
            f"/api/projects/{sid}/issues/{issue_id}/reopen",
            json={"note": "Try again"},
            headers=auth_headers,
        )
        db.expire_all()
        assert attention_service.count_pending(db, user_id) == 0

        client.post(
            f"/api/projects/{sid}/issues/{issue_id}/developer-complete",
            headers=auth_headers,
        )
        db.expire_all()
        second_pending = attention_service.list_pending(db, user_id)
        assert len(second_pending) == 1
        second_item_id = second_pending[0].id

        assert second_item_id != first_item_id
        assert second_pending[0].source_id == issue_id
        assert second_pending[0].source_type == (
            attention_service.SOURCE_TYPE_DEVELOPER_COMPLETION_ISSUE
        )

    def test_issue_attention_adapter_provides_expected_fields(
        self, client, auth_headers,
    ):
        sid = _create_project(client, auth_headers, "DC Issue Adapter")
        email = _user_email(client, auth_headers)
        issue_id = _create_issue(sid, "Adapter description")

        r = client.post(
            f"/api/projects/{sid}/issues/{issue_id}/developer-complete",
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text

        items = client.get("/api/inbox", headers=auth_headers).json()["items"]
        assert len(items) == 1
        item = items[0]
        assert item["source_type"] == (
            attention_service.SOURCE_TYPE_DEVELOPER_COMPLETION_ISSUE
        )
        assert item["title"] == "Issue: Adapter description"
        assert item["subtitle"] is not None
        assert "test_failure" in item["subtitle"]
        assert "severity medium" in item["subtitle"]
        assert f"completed by {email}" in item["subtitle"]
        assert item["context_url"] == (
            f"/p/{sid}/issues?focus=issue:{issue_id}"
        )

    def test_test_case_attention_adapter_provides_expected_fields(
        self, client, auth_headers,
    ):
        sid = _create_project(client, auth_headers, "DC TC Adapter")
        email = _user_email(client, auth_headers)
        tc_id = _create_test_case(sid, "TC-ADP", "Adapter scenario")

        r = client.post(
            f"/api/projects/{sid}/test-cases/{tc_id}/developer-complete",
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text

        items = client.get("/api/inbox", headers=auth_headers).json()["items"]
        assert len(items) == 1
        item = items[0]
        assert item["source_type"] == (
            attention_service.SOURCE_TYPE_DEVELOPER_COMPLETION_TEST_CASE
        )
        assert item["title"] == "Test case: TC-ADP Adapter scenario"
        assert item["subtitle"] is not None
        assert "QA" in item["subtitle"]
        assert "priority Medium" in item["subtitle"]
        assert f"completed by {email}" in item["subtitle"]
        assert item["context_url"] == (
            f"/p/{sid}/testing?focus=test_case:{tc_id}"
        )


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------
_ISSUE_ENDPOINT_SUFFIXES = ("developer-complete", "confirm", "reopen")
_TC_ENDPOINT_SUFFIXES = ("developer-complete", "confirm", "reopen")


class TestAuthorization:
    @pytest.mark.parametrize("suffix", _ISSUE_ENDPOINT_SUFFIXES)
    @pytest.mark.parametrize("entity", ["issue", "test-case"])
    def test_workflow_endpoints_require_authentication(
        self, client, entity, suffix,
    ):
        entity_id = uuid.uuid4().hex
        path = (
            f"/api/projects/whatever/{entity}s/{entity_id}/{suffix}"
        )
        body = {"note": "x"} if suffix == "reopen" else None
        r = client.post(path, json=body)
        assert r.status_code == 401

    def test_developer_can_complete_but_cannot_confirm_or_reopen(
        self, client, auth_headers, db, cleanup_registry,
    ):
        """The Developer role holds ISSUES_WRITE but not REVIEWS_SUBMIT.
        On an org-owned project the Developer is a member of, they can
        mark complete but cannot confirm or reopen."""
        fc_id = _user_id(client, auth_headers)
        org_id = _insert_org_with_owner(db, fc_id, "DC Role Org")
        cleanup_registry.org_ids.append(org_id)

        dev_headers = _signup_with_role(client, cleanup_registry, "developer")
        dev_id = _user_id(client, dev_headers)
        _insert_membership(db, dev_id, org_id, "member")

        sid = _create_project(
            client, auth_headers, "DC Role Project",
            organization_id=org_id,
        )
        issue_id = _create_issue(sid)

        # Developer can complete.
        r = client.post(
            f"/api/projects/{sid}/issues/{issue_id}/developer-complete",
            headers=dev_headers,
        )
        assert r.status_code == 200, r.text

        # Developer cannot confirm.
        r = client.post(
            f"/api/projects/{sid}/issues/{issue_id}/confirm",
            headers=dev_headers,
        )
        assert r.status_code == 403

        # Developer cannot reopen.
        r = client.post(
            f"/api/projects/{sid}/issues/{issue_id}/reopen",
            json={"note": "n/a"},
            headers=dev_headers,
        )
        assert r.status_code == 403

    @pytest.mark.parametrize("suffix", _ISSUE_ENDPOINT_SUFFIXES)
    @pytest.mark.parametrize("entity", ["issue", "test-case"])
    def test_business_development_cannot_invoke_workflow_endpoints(
        self, client, cleanup_registry, entity, suffix,
    ):
        headers = _signup_with_role(client, cleanup_registry, "business_development")
        entity_id = uuid.uuid4().hex
        path = f"/api/projects/whatever/{entity}s/{entity_id}/{suffix}"
        body = {"note": "x"} if suffix == "reopen" else None
        r = client.post(path, json=body, headers=headers)
        assert r.status_code == 403

    def test_cross_user_operation_returns_404(
        self, client, auth_headers, cleanup_registry,
    ):
        """Two independent personal projects owned by two different FCs.
        Neither can invoke the workflow on the other's session (tenant
        boundary) or on their own session with a foreign entity id
        (service-level session guard)."""
        sid_a = _create_project(client, auth_headers, "DC Cross A")
        issue_a = _create_issue(sid_a)

        headers_b = _signup_with_role(
            client, cleanup_registry, "functional_consultant",
        )
        sid_b = _create_project(client, headers_b, "DC Cross B")

        # B tries A's session with A's issue id.
        r = client.post(
            f"/api/projects/{sid_a}/issues/{issue_a}/developer-complete",
            headers=headers_b,
        )
        assert r.status_code == 404

        # B tries own session with A's issue id.
        r = client.post(
            f"/api/projects/{sid_b}/issues/{issue_a}/developer-complete",
            headers=headers_b,
        )
        assert r.status_code == 404