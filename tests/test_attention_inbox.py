"""
Integration tests for the unified consultant inbox.

Scope:
  * Pending listing, history listing, pending count.
  * Recipient isolation: every query filters on recipient_user_id.
  * Resolve semantics: success, wrong-recipient 404, unknown-id 404,
    already-resolved 404.
  * Adapter-backed presentation fields (title / subtitle / context_url)
    coming from a registered source adapter.
  * Adapter fallback: source record missing -> stub display.
  * Phase 2.9 bid-won adapter rule: session_id absent -> context_url
    is None (no route into a Business Development-only surface).
  * Phase 2.9 `resolved_by_user_id` field on resolved items.
  * Authorization: INBOX_READ enforced on every endpoint.

Fixtures (from tests/conftest.py):
    * client            TestClient(app) with lifespan.
    * auth_headers      fresh functional_consultant (holds INBOX_READ).
    * cleanup_registry  tracks users, orgs, opportunities for teardown.

Direct database setup:
    There is no HTTP path for creating AttentionItem rows in isolation;
    they are produced as a side effect of the source workflows (ERP User
    requests, developer completion, bid won). This file therefore creates
    AttentionItem rows via the attention_service public API against the
    shared SessionLocal, and the source records (ErpUserRequest,
    Opportunity, Organization) via the same session. Every created user,
    organization, and opportunity is registered with cleanup_registry so
    the shared PostgreSQL database is left clean.

PostgreSQL only: no SQLite branches, no DATABASE_URL override, no
transaction-rollback isolation.
"""
from __future__ import annotations

import uuid
from typing import Dict

import pytest

from src.db.base import SessionLocal
from src.db.models import (
    Opportunity,
    Organization,
    OrganizationMembership,
    SessionRecord,
)
from src.services import attention_service
from src.services import erp_user_requests as erp_user_requests_svc
from tests._auth_helpers import signup_and_authenticate
from tests.conftest import unique_email


# ---------------------------------------------------------------------------
# Local helpers
# ---------------------------------------------------------------------------
def _signup_with_role(
    client, cleanup_registry, role: str,
) -> Dict[str, str]:
    """Sign up a fresh user with the given account_type, complete the
    auth flow, and return Bearer authorization headers. Registers the
    user's email with cleanup_registry."""
    email = unique_email(f"inbox-{role}")
    cleanup_registry.emails.append(email)
    token = signup_and_authenticate(client, email=email, account_type=role)
    return {"Authorization": f"Bearer {token}"}


def _user_id(client, headers: Dict[str, str]) -> str:
    r = client.get("/api/auth/me", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["id"]


@pytest.fixture
def db():
    """A plain SessionLocal for direct setup of AttentionItem rows.

    The application opens its own session per HTTP request. This one is
    only used by the test to seed and inspect data. Both target the same
    PostgreSQL database, so a commit here is immediately visible to the
    running application."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _make_item(
    db,
    *,
    recipient_user_id: str,
    source_type: str,
    source_id: str | None = None,
    session_id: str | None = None,
    organization_id: str | None = None,
) -> str:
    """Create an AttentionItem and commit. Returns the item id.

    Idempotent per the service contract - a second call for the same
    (source_type, source_id, recipient) returns the existing pending
    item."""
    item = attention_service.create_attention_item(
        db,
        recipient_user_id=recipient_user_id,
        source_type=source_type,
        source_id=source_id or uuid.uuid4().hex,
        session_id=session_id,
        organization_id=organization_id,
    )
    db.commit()
    return item.id


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


def _insert_opportunity(
    db, *, org_id: str, user_id: str, title: str,
) -> str:
    opp_id = uuid.uuid4().hex
    db.add(Opportunity(
        id=opp_id,
        organization_id=org_id,
        created_by_user_id=user_id,
        owner_user_id=user_id,
        title=title,
        client_name="Test Client",
        status="won",
    ))
    db.commit()
    return opp_id


def _insert_erp_user_request(
    db, *, session_id: str, user_id: str, subject: str,
) -> str:
    """Insert an ErpUserRequest row directly via the service.

    The service path is used instead of the HTTP route because the route
    additionally requires an active artifact grant, which is orthogonal
    to what this test exercises. The service also fans out the
    corresponding attention item, which is the item this file asserts on.
    Returns the request id."""
    sess = db.get(SessionRecord, session_id)
    assert sess is not None
    request = erp_user_requests_svc.create_request(
        db,
        session=sess,
        created_by_user_id=user_id,
        request_type="question",
        subject=subject,
        body="Body",
    )
    db.commit()
    return request.id


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------
class TestInboxAuthorization:
    def test_pending_listing_requires_authentication(self, client):
        r = client.get("/api/inbox")
        assert r.status_code == 401

    def test_history_listing_requires_authentication(self, client):
        r = client.get("/api/inbox/history")
        assert r.status_code == 401

    def test_count_requires_authentication(self, client):
        r = client.get("/api/inbox/count")
        assert r.status_code == 401

    def test_resolve_requires_authentication(self, client):
        r = client.post("/api/inbox/whatever/resolve")
        assert r.status_code == 401

    def test_pending_listing_requires_inbox_read_capability(
        self, client, cleanup_registry,
    ):
        # Developer does not hold INBOX_READ -> 403, not an empty list.
        headers = _signup_with_role(client, cleanup_registry, "developer")
        r = client.get("/api/inbox", headers=headers)
        assert r.status_code == 403

    def test_history_listing_requires_inbox_read_capability(
        self, client, cleanup_registry,
    ):
        headers = _signup_with_role(client, cleanup_registry, "developer")
        r = client.get("/api/inbox/history", headers=headers)
        assert r.status_code == 403

    def test_count_requires_inbox_read_capability(
        self, client, cleanup_registry,
    ):
        headers = _signup_with_role(client, cleanup_registry, "developer")
        r = client.get("/api/inbox/count", headers=headers)
        assert r.status_code == 403

    def test_resolve_requires_inbox_read_capability(
        self, client, cleanup_registry,
    ):
        headers = _signup_with_role(client, cleanup_registry, "developer")
        r = client.post("/api/inbox/whatever/resolve", headers=headers)
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------
class TestInboxListing:
    def test_pending_listing_is_empty_for_new_user(
        self, client, auth_headers,
    ):
        r = client.get("/api/inbox", headers=auth_headers)
        assert r.status_code == 200
        assert r.json() == {"items": []}

    def test_history_listing_is_empty_for_new_user(
        self, client, auth_headers,
    ):
        r = client.get("/api/inbox/history", headers=auth_headers)
        assert r.status_code == 200
        assert r.json() == {"items": []}

    def test_pending_listing_returns_my_items_newest_first(
        self, client, auth_headers, db,
    ):
        user_id = _user_id(client, auth_headers)
        _make_item(
            db, recipient_user_id=user_id,
            source_type=attention_service.SOURCE_TYPE_BID_WON,
        )
        second_id = _make_item(
            db, recipient_user_id=user_id,
            source_type=attention_service.SOURCE_TYPE_BID_WON,
        )

        r = client.get("/api/inbox", headers=auth_headers)
        assert r.status_code == 200
        items = r.json()["items"]
        assert len(items) == 2
        # Newest first (created_at DESC).
        assert items[0]["id"] == second_id
        # Pending items do not carry a resolver.
        assert items[0]["resolved_by_user_id"] is None
        assert items[0]["resolved_at"] is None

    def test_history_listing_returns_my_resolved_items(
        self, client, auth_headers, db,
    ):
        user_id = _user_id(client, auth_headers)
        item_id = _make_item(
            db, recipient_user_id=user_id,
            source_type=attention_service.SOURCE_TYPE_BID_WON,
        )
        assert attention_service.resolve_attention_item(db, item_id, user_id)
        db.commit()

        r = client.get("/api/inbox/history", headers=auth_headers)
        assert r.status_code == 200
        ids = {i["id"] for i in r.json()["items"]}
        assert item_id in ids

    def test_resolved_items_do_not_appear_in_pending_listing(
        self, client, auth_headers, db,
    ):
        user_id = _user_id(client, auth_headers)
        item_id = _make_item(
            db, recipient_user_id=user_id,
            source_type=attention_service.SOURCE_TYPE_BID_WON,
        )
        assert attention_service.resolve_attention_item(db, item_id, user_id)
        db.commit()

        r = client.get("/api/inbox", headers=auth_headers)
        ids = {i["id"] for i in r.json()["items"]}
        assert item_id not in ids


# ---------------------------------------------------------------------------
# Recipient isolation
# ---------------------------------------------------------------------------
class TestRecipientIsolation:
    def test_items_are_isolated_between_recipients(
        self, client, auth_headers, db, cleanup_registry,
    ):
        user_a = _user_id(client, auth_headers)
        headers_b = _signup_with_role(
            client, cleanup_registry, "functional_consultant",
        )
        user_b = _user_id(client, headers_b)

        item_a = _make_item(
            db, recipient_user_id=user_a,
            source_type=attention_service.SOURCE_TYPE_BID_WON,
        )
        item_b = _make_item(
            db, recipient_user_id=user_b,
            source_type=attention_service.SOURCE_TYPE_BID_WON,
        )

        a_items = {
            i["id"] for i in client.get(
                "/api/inbox", headers=auth_headers,
            ).json()["items"]
        }
        b_items = {
            i["id"] for i in client.get(
                "/api/inbox", headers=headers_b,
            ).json()["items"]
        }

        assert item_a in a_items
        assert item_a not in b_items
        assert item_b in b_items
        assert item_b not in a_items

    def test_count_is_recipient_scoped(
        self, client, auth_headers, db, cleanup_registry,
    ):
        user_a = _user_id(client, auth_headers)
        headers_b = _signup_with_role(
            client, cleanup_registry, "functional_consultant",
        )
        user_b = _user_id(client, headers_b)

        _make_item(db, recipient_user_id=user_a,
                   source_type=attention_service.SOURCE_TYPE_BID_WON)
        _make_item(db, recipient_user_id=user_a,
                   source_type=attention_service.SOURCE_TYPE_BID_WON)
        _make_item(db, recipient_user_id=user_b,
                   source_type=attention_service.SOURCE_TYPE_BID_WON)

        a_count = client.get(
            "/api/inbox/count", headers=auth_headers,
        ).json()
        b_count = client.get(
            "/api/inbox/count", headers=headers_b,
        ).json()

        assert a_count == {"pending": 2}
        assert b_count == {"pending": 1}


# ---------------------------------------------------------------------------
# Count
# ---------------------------------------------------------------------------
class TestPendingCount:
    def test_count_starts_at_zero_for_new_user(self, client, auth_headers):
        r = client.get("/api/inbox/count", headers=auth_headers)
        assert r.status_code == 200
        assert r.json() == {"pending": 0}

    def test_count_reflects_pending_only(self, client, auth_headers, db):
        user_id = _user_id(client, auth_headers)
        _make_item(db, recipient_user_id=user_id,
                   source_type=attention_service.SOURCE_TYPE_BID_WON)
        resolved_id = _make_item(db, recipient_user_id=user_id,
                                 source_type=attention_service.SOURCE_TYPE_BID_WON)
        assert attention_service.resolve_attention_item(db, resolved_id, user_id)
        db.commit()

        r = client.get("/api/inbox/count", headers=auth_headers)
        assert r.json() == {"pending": 1}


# ---------------------------------------------------------------------------
# Resolve
# ---------------------------------------------------------------------------
class TestResolve:
    def test_resolve_pending_item_succeeds(self, client, auth_headers, db):
        user_id = _user_id(client, auth_headers)
        item_id = _make_item(
            db, recipient_user_id=user_id,
            source_type=attention_service.SOURCE_TYPE_BID_WON,
        )

        r = client.post(f"/api/inbox/{item_id}/resolve", headers=auth_headers)
        assert r.status_code == 200
        assert r.json() == {"resolved": True}

        pending_ids = {
            i["id"] for i in client.get(
                "/api/inbox", headers=auth_headers,
            ).json()["items"]
        }
        history_ids = {
            i["id"] for i in client.get(
                "/api/inbox/history", headers=auth_headers,
            ).json()["items"]
        }
        assert item_id not in pending_ids
        assert item_id in history_ids

    def test_resolve_unknown_item_returns_404(self, client, auth_headers):
        r = client.post(
            f"/api/inbox/{uuid.uuid4().hex}/resolve",
            headers=auth_headers,
        )
        assert r.status_code == 404

    def test_resolve_wrong_recipient_returns_404(
        self, client, auth_headers, db, cleanup_registry,
    ):
        """The response must not distinguish 'not yours' from 'no such
        item'. Item must remain pending for the correct recipient."""
        user_a = _user_id(client, auth_headers)
        item_id = _make_item(
            db, recipient_user_id=user_a,
            source_type=attention_service.SOURCE_TYPE_BID_WON,
        )

        headers_b = _signup_with_role(
            client, cleanup_registry, "functional_consultant",
        )
        r = client.post(
            f"/api/inbox/{item_id}/resolve", headers=headers_b,
        )
        assert r.status_code == 404

        a_pending = {
            i["id"] for i in client.get(
                "/api/inbox", headers=auth_headers,
            ).json()["items"]
        }
        assert item_id in a_pending

    def test_resolve_already_resolved_returns_404(
        self, client, auth_headers, db,
    ):
        user_id = _user_id(client, auth_headers)
        item_id = _make_item(
            db, recipient_user_id=user_id,
            source_type=attention_service.SOURCE_TYPE_BID_WON,
        )

        r = client.post(f"/api/inbox/{item_id}/resolve", headers=auth_headers)
        assert r.status_code == 200

        r = client.post(f"/api/inbox/{item_id}/resolve", headers=auth_headers)
        assert r.status_code == 404

    def test_resolved_item_exposes_resolved_by_user_id(
        self, client, auth_headers, db,
    ):
        """Phase 2.9 added `resolved_by_user_id` to the wire shape."""
        user_id = _user_id(client, auth_headers)
        item_id = _make_item(
            db, recipient_user_id=user_id,
            source_type=attention_service.SOURCE_TYPE_BID_WON,
        )
        r = client.post(f"/api/inbox/{item_id}/resolve", headers=auth_headers)
        assert r.status_code == 200

        history = client.get(
            "/api/inbox/history", headers=auth_headers,
        ).json()["items"]
        item = next(i for i in history if i["id"] == item_id)
        assert item["resolved_by_user_id"] == user_id
        assert item["resolved_at"] is not None


# ---------------------------------------------------------------------------
# Adapter presentation
# ---------------------------------------------------------------------------
class TestAdapterPresentation:
    def test_erp_user_request_adapter_provides_title_subtitle_and_url(
        self, client, auth_headers, db,
    ):
        """When the source record exists, the registered adapter supplies
        the presentation fields. Exercised against the ERP User request
        adapter because its setup requires only a personal project and a
        request row."""
        user_id = _user_id(client, auth_headers)
        r = client.post(
            "/api/projects/start",
            json={"project_name": "Inbox Adapter Test", "module": "FI"},
            headers=auth_headers,
        )
        assert r.status_code == 200
        session_id = r.json()["session_id"]

        request_id = _insert_erp_user_request(
            db,
            session_id=session_id,
            user_id=user_id,
            subject="Adapters in the inbox",
        )

        r = client.get("/api/inbox", headers=auth_headers)
        items = r.json()["items"]
        assert len(items) == 1
        item = items[0]
        assert item["source_type"] == attention_service.SOURCE_TYPE_ERP_USER_REQUEST
        assert item["title"] == "Adapters in the inbox"
        assert item["subtitle"] is not None
        assert "question" in item["subtitle"]
        assert item["context_url"] == (
            f"/p/{session_id}/support?focus=erp-user-request:{request_id}"
        )

    def test_missing_source_record_falls_back_to_stub(
        self, client, auth_headers, db,
    ):
        """An adapter returning None (source row missing) must not drop
        the item - the API layer substitutes a stub."""
        user_id = _user_id(client, auth_headers)
        _make_item(
            db,
            recipient_user_id=user_id,
            source_type=attention_service.SOURCE_TYPE_ERP_USER_REQUEST,
            source_id=uuid.uuid4().hex,  # does not exist
        )

        r = client.get("/api/inbox", headers=auth_headers)
        items = r.json()["items"]
        assert len(items) == 1
        item = items[0]
        assert item["title"] == "Erp User Request"
        assert item["subtitle"] is None
        assert item["context_url"] is None

    def test_bid_won_adapter_returns_null_url_when_session_missing(
        self, client, auth_headers, db, cleanup_registry,
    ):
        """Phase 2.9: the bid-won adapter must not route the consultant
        to /opportunities (a Business Development surface) when the
        session_id is absent. context_url is None."""
        user_id = _user_id(client, auth_headers)
        org_id = _insert_org_with_owner(db, user_id, "Inbox Bid Won Org")
        cleanup_registry.org_ids.append(org_id)

        opp_id = _insert_opportunity(
            db, org_id=org_id, user_id=user_id, title="Test Tender",
        )
        cleanup_registry.opportunity_ids.append(opp_id)

        _make_item(
            db,
            recipient_user_id=user_id,
            source_type=attention_service.SOURCE_TYPE_BID_WON,
            source_id=opp_id,
            session_id=None,
            organization_id=org_id,
        )

        r = client.get("/api/inbox", headers=auth_headers)
        items = r.json()["items"]
        assert len(items) == 1
        item = items[0]
        assert item["title"] == "New project: Test Tender"
        assert item["subtitle"] == "Client: Test Client"
        assert item["context_url"] is None

    def test_bid_won_adapter_routes_to_project_when_session_present(
        self, client, auth_headers, db, cleanup_registry,
    ):
        """With a session_id present, the bid-won adapter routes to
        /p/{session_id}."""
        user_id = _user_id(client, auth_headers)
        r = client.post(
            "/api/projects/start",
            json={"project_name": "Bid Won Project", "module": "FI"},
            headers=auth_headers,
        )
        assert r.status_code == 200
        session_id = r.json()["session_id"]

        org_id = _insert_org_with_owner(db, user_id, "Inbox Bid Won Org 2")
        cleanup_registry.org_ids.append(org_id)
        opp_id = _insert_opportunity(
            db, org_id=org_id, user_id=user_id, title="Bid Won Opp",
        )
        cleanup_registry.opportunity_ids.append(opp_id)

        _make_item(
            db,
            recipient_user_id=user_id,
            source_type=attention_service.SOURCE_TYPE_BID_WON,
            source_id=opp_id,
            session_id=session_id,
            organization_id=org_id,
        )

        item = client.get(
            "/api/inbox", headers=auth_headers,
        ).json()["items"][0]
        assert item["context_url"] == f"/p/{session_id}"


# ---------------------------------------------------------------------------
# Source types
# ---------------------------------------------------------------------------
class TestSourceTypes:
    def test_all_four_source_types_are_listed_independently(
        self, client, auth_headers, db,
    ):
        """The four registered source types round-trip through the inbox
        with their source_type strings intact. No deduplication across
        source types occurs."""
        user_id = _user_id(client, auth_headers)
        for source_type in (
            attention_service.SOURCE_TYPE_BID_WON,
            attention_service.SOURCE_TYPE_DEVELOPER_COMPLETION_ISSUE,
            attention_service.SOURCE_TYPE_DEVELOPER_COMPLETION_TEST_CASE,
            attention_service.SOURCE_TYPE_ERP_USER_REQUEST,
        ):
            _make_item(
                db,
                recipient_user_id=user_id,
                source_type=source_type,
                source_id=uuid.uuid4().hex,
            )

        items = client.get("/api/inbox", headers=auth_headers).json()["items"]
        assert len(items) == 4
        assert {i["source_type"] for i in items} == {
            attention_service.SOURCE_TYPE_BID_WON,
            attention_service.SOURCE_TYPE_DEVELOPER_COMPLETION_ISSUE,
            attention_service.SOURCE_TYPE_DEVELOPER_COMPLETION_TEST_CASE,
            attention_service.SOURCE_TYPE_ERP_USER_REQUEST,
        }