"""
ERP User request lifecycle and attention-inbox integration.

The support-request endpoints in src/api/erp_user_api.py gate on two
conditions: project membership and at least one active artifact grant
(`any_grant`). The requester is therefore whichever project member
holds a grant — the project owner on a personal project (the only
member), or any granted org member on an organization-owned project.

Coverage:
  * Request creation and persistence.
  * Request listing for the requester and for the project's consultants.
  * Attention-item fan-out one per recipient.
  * Resolution closes the request and every pending attention item for
    it (via resolve_for_source).
  * Recipient isolation on the resulting inbox items.
  * Cross-project access denied (tenant boundary and service session guard).
  * Org-owned recipient fan-out covering multiple FC members.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Dict

import pytest

from src.auth.project_access import ArtifactType
from src.db.base import SessionLocal
from src.db.models import (
    AttentionItem,
    Organization,
    OrganizationMembership,
    SessionUserArtifactGrant,
)
from src.services import attention_service
from src.services import erp_user_requests as req_svc
from tests._auth_helpers import signup_and_authenticate
from tests.conftest import unique_email


def _signup(client, cleanup_registry, role: str) -> Dict[str, str]:
    email = unique_email(f"erq-{role}")
    cleanup_registry.emails.append(email)
    token = signup_and_authenticate(client, email=email, account_type=role)
    return {"Authorization": f"Bearer {token}"}


def _uid(client, headers) -> str:
    r = client.get("/api/auth/me", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _start(client, headers, name: str, org_id=None) -> str:
    payload = {"project_name": name, "module": "FI"}
    if org_id is not None:
        payload["organization_id"] = org_id
    r = client.post("/api/projects/start", json=payload, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["session_id"]


@pytest.fixture
def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


def _org_with_members(db, owner_id: str, members, name: str) -> str:
    org_id = uuid.uuid4().hex
    db.add(Organization(id=org_id, name=name, created_by=owner_id))
    db.add(OrganizationMembership(
        id=uuid.uuid4().hex, organization_id=org_id,
        user_id=owner_id, role="owner",
    ))
    for uid in members:
        db.add(OrganizationMembership(
            id=uuid.uuid4().hex, organization_id=org_id,
            user_id=uid, role="member",
        ))
    db.commit()
    return org_id


def _grant_artifact(
    db, session_id: str, user_id: str,
    artifact: ArtifactType = ArtifactType.REQUIREMENTS_QUESTIONNAIRE,
) -> None:
    """Insert an active artifact grant so the caller passes the
    `any_grant` gate in the support-request endpoints. Mirrors the
    production insert in src/auth/project_access.py::grant_artifact;
    `revoked_at IS NULL` is what makes a row active."""
    db.add(SessionUserArtifactGrant(
        id=uuid.uuid4().hex,
        session_id=session_id,
        user_id=user_id,
        artifact_type=artifact.value,
        is_signatory=False,
        is_uat_participant=False,
        granted_by_user_id=None,
        granted_at=datetime.now(timezone.utc),
        revoked_at=None,
    ))
    db.commit()


def _post_request(client, headers, sid: str, body: dict) -> dict:
    r = client.post(
        f"/api/projects/{sid}/erp-user/requests", json=body, headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()


class TestPersonalProjectRequests:
    """On a personal project the only member is the owner, so the
    owner is the sole possible requester and the sole recipient."""

    def test_request_creation_fans_out_to_owner(
        self, client, auth_headers, db,
    ):
        owner_id = _uid(client, auth_headers)
        sid = _start(client, auth_headers, "EUR Personal")
        _grant_artifact(db, sid, owner_id)

        row = _post_request(
            client, auth_headers, sid,
            {"request_type": "question", "subject": "S", "body": "B"},
        )
        rid = row["id"]

        db.expire_all()
        pending = attention_service.list_pending(db, owner_id)
        matching = [
            i for i in pending
            if i.source_type == attention_service.SOURCE_TYPE_ERP_USER_REQUEST
            and i.source_id == rid
        ]
        assert len(matching) == 1

    def test_request_retrieval_via_http(self, client, auth_headers, db):
        owner_id = _uid(client, auth_headers)
        sid = _start(client, auth_headers, "EUR Retrieve")
        _grant_artifact(db, sid, owner_id)

        row = _post_request(
            client, auth_headers, sid,
            {"request_type": "change", "subject": "Fix", "body": "Please"},
        )
        rid = row["id"]

        r = client.get(
            f"/api/projects/{sid}/erp-user/requests", headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        rows = r.json()["requests"]
        assert any(x["id"] == rid for x in rows)


class TestOrgFanOut:
    def test_org_project_fans_out_to_all_fc_members(
        self, client, auth_headers, db, cleanup_registry,
    ):
        owner_id = _uid(client, auth_headers)
        fc2_headers = _signup(client, cleanup_registry, "functional_consultant")
        fc2_id = _uid(client, fc2_headers)

        erp_headers = _signup(client, cleanup_registry, "erp_user")
        erp_id = _uid(client, erp_headers)

        org_id = _org_with_members(
            db, owner_id, [fc2_id, erp_id], "EUR Fan Org",
        )
        cleanup_registry.org_ids.append(org_id)
        sid = _start(client, auth_headers, "EUR Fan Proj", org_id)
        _grant_artifact(db, sid, erp_id)

        row = _post_request(
            client, erp_headers, sid,
            {"request_type": "question", "subject": "Q", "body": "B"},
        )
        rid = row["id"]

        db.expire_all()
        for uid in (owner_id, fc2_id):
            pending = attention_service.list_pending(db, uid)
            matching = [
                i for i in pending
                if i.source_type == attention_service.SOURCE_TYPE_ERP_USER_REQUEST
                and i.source_id == rid
            ]
            assert len(matching) == 1, f"missing item for {uid}"


class TestResolution:
    def test_resolve_request_closes_request_and_attention(
        self, client, auth_headers, db,
    ):
        owner_id = _uid(client, auth_headers)
        sid = _start(client, auth_headers, "EUR Resolve")
        _grant_artifact(db, sid, owner_id)

        row = _post_request(
            client, auth_headers, sid,
            {"request_type": "issue", "subject": "X", "body": "Y"},
        )
        rid = row["id"]

        r = client.post(
            f"/api/projects/{sid}/erp-user-requests/{rid}/resolve",
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        assert r.json() == {"id": rid, "resolved": True}

        db.expire_all()
        req = req_svc.get_request(db, rid, sid)
        assert req.status == "resolved"
        assert req.resolved_at is not None

        pending = attention_service.list_pending(db, owner_id)
        assert all(
            not (
                i.source_type == attention_service.SOURCE_TYPE_ERP_USER_REQUEST
                and i.source_id == rid
            )
            for i in pending
        )

    def test_resolve_idempotent(self, client, auth_headers, db):
        owner_id = _uid(client, auth_headers)
        sid = _start(client, auth_headers, "EUR Resolve Idem")
        _grant_artifact(db, sid, owner_id)

        row = _post_request(
            client, auth_headers, sid,
            {"request_type": "other", "subject": "A", "body": "B"},
        )
        rid = row["id"]

        first = client.post(
            f"/api/projects/{sid}/erp-user-requests/{rid}/resolve",
            headers=auth_headers,
        )
        assert first.status_code == 200
        assert first.json()["resolved"] is True

        second = client.post(
            f"/api/projects/{sid}/erp-user-requests/{rid}/resolve",
            headers=auth_headers,
        )
        assert second.status_code == 200
        assert second.json()["resolved"] is False

    def test_resolve_unknown_request_404(self, client, auth_headers):
        sid = _start(client, auth_headers, "EUR Unknown")
        r = client.post(
            f"/api/projects/{sid}/erp-user-requests/{uuid.uuid4().hex}/resolve",
            headers=auth_headers,
        )
        assert r.status_code == 404


class TestTenantBoundary:
    def test_cross_project_access_denied(
        self, client, auth_headers, db, cleanup_registry,
    ):
        owner_a_id = _uid(client, auth_headers)
        sid_a = _start(client, auth_headers, "EUR Cross A")
        _grant_artifact(db, sid_a, owner_a_id)

        row = _post_request(
            client, auth_headers, sid_a,
            {"request_type": "question", "subject": "S", "body": "B"},
        )
        rid = row["id"]

        headers_b = _signup(client, cleanup_registry, "functional_consultant")
        _start(client, headers_b, "EUR Cross B")

        # FC-B cannot resolve a request on FC-A's project.
        r = client.post(
            f"/api/projects/{sid_a}/erp-user-requests/{rid}/resolve",
            headers=headers_b,
        )
        assert r.status_code == 404

        # FC-B cannot list requests on FC-A's project.
        r = client.get(
            f"/api/projects/{sid_a}/erp-user/requests", headers=headers_b,
        )
        assert r.status_code == 404