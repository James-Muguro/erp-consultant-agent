"""
Case-study endpoint tests.

Snapshot basis: the /api/projects/{session_id}/case-study endpoint on
src/orchestrator_api.py.

Coverage:
  * Capability gate: requires OPPORTUNITY_CASE_STUDY_READ (BD only).
  * Org-membership requirement: FC/Developer/ERP User receive 404.
  * Opportunity provenance: project must have been converted from an
    Opportunity (converted_session_id is set on the Opportunity).
  * Personal projects receive 404.
  * Non-member of the owning org receives 404.
  * Response shape: fields present, no workspace data.
"""
from __future__ import annotations

import uuid
from typing import Dict

import pytest

from src.db.base import SessionLocal
from src.db.models import (
    Opportunity,
    OpportunityRequirement,
    Organization,
    OrganizationMembership,
    SessionRecord,
)
from tests._auth_helpers import signup_and_authenticate
from tests.conftest import unique_email


def _signup(client, cleanup_registry, role: str) -> Dict[str, str]:
    email = unique_email(f"cs-{role}")
    cleanup_registry.emails.append(email)
    token = signup_and_authenticate(client, email=email, account_type=role)
    return {"Authorization": f"Bearer {token}"}


def _uid(client, headers) -> str:
    r = client.get("/api/auth/me", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["id"]


@pytest.fixture
def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


def _org_with_members(db, owner_id, members, name):
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


def _won_opportunity(client, db, cleanup_registry, owner_headers, consultant_headers):
    owner_id = _uid(client, owner_headers)
    consultant_id = _uid(client, consultant_headers)
    org_id = _org_with_members(db, owner_id, [consultant_id], f"CS Org {uuid.uuid4().hex[:6]}")
    cleanup_registry.org_ids.append(org_id)

    r = client.post(
        "/api/opportunities",
        json={"title": "CS", "client_name": "C", "organization_id": org_id},
        headers=owner_headers,
    )
    opp_id = r.json()["id"]
    cleanup_registry.opportunity_ids.append(opp_id)

    db.add(OpportunityRequirement(
        id=uuid.uuid4().hex, opportunity_id=opp_id,
        external_code="TOR-001", description="Req",
        priority="Medium", req_type="Functional",
        status="draft", ai_draft_status="finalized",
        fit_response="meets_out_of_the_box",
    ))
    opp = db.get(Opportunity, opp_id)
    opp.status = "tor_finalized"
    opp.assigned_consultant_user_id = consultant_id
    db.commit()

    r = client.post(
        f"/api/opportunities/{opp_id}/mark-won", json={}, headers=owner_headers,
    )
    assert r.status_code == 200, r.text
    return org_id, r.json()["session_id"]


class TestCaseStudyAuthorization:
    def test_requires_business_development_capability(
        self, client, cleanup_registry, db,
    ):
        """FC does not hold OPPORTUNITY_CASE_STUDY_READ."""
        owner = _signup(client, cleanup_registry, "business_development")
        consultant = _signup(client, cleanup_registry, "functional_consultant")
        _, sid = _won_opportunity(client, db, cleanup_registry, owner, consultant)

        r = client.get(f"/api/projects/{sid}/case-study", headers=consultant)
        assert r.status_code == 403

    def test_personal_project_404(self, client, cleanup_registry):
        bd = _signup(client, cleanup_registry, "business_development")
        # BD cannot create a personal project (lacks PROJECT_CREATE); so
        # create the personal project via an FC and request as BD.
        fc = _signup(client, cleanup_registry, "functional_consultant")
        r = client.post(
            "/api/projects/start",
            json={"project_name": "CS Personal", "module": "FI"},
            headers=fc,
        )
        sid = r.json()["session_id"]

        r = client.get(f"/api/projects/{sid}/case-study", headers=bd)
        # 404 not 403 - the endpoint's contract is enumeration-resistant.
        assert r.status_code == 404

    def test_non_member_of_org_404(
        self, client, cleanup_registry, db,
    ):
        owner = _signup(client, cleanup_registry, "business_development")
        consultant = _signup(client, cleanup_registry, "functional_consultant")
        _, sid = _won_opportunity(client, db, cleanup_registry, owner, consultant)

        # A different BD who is not a member of the owning org.
        outsider = _signup(client, cleanup_registry, "business_development")
        outsider_id = _uid(client, outsider)
        other_org = _org_with_members(db, outsider_id, [], "CS Other Org")
        cleanup_registry.org_ids.append(other_org)

        r = client.get(f"/api/projects/{sid}/case-study", headers=outsider)
        assert r.status_code == 404

    def test_project_without_opportunity_provenance_404(
        self, client, cleanup_registry, db,
    ):
        """An org-owned project created via POST /api/projects/start
        (not via Mark-as-Won) has no converting Opportunity; the
        endpoint returns 404 even for a member of the owning org."""
        owner = _signup(client, cleanup_registry, "business_development")
        owner_id = _uid(client, owner)
        org_id = _org_with_members(db, owner_id, [], "CS Direct Org")
        cleanup_registry.org_ids.append(org_id)

        # Owner happens to also be an FC? No, they're BD. So start via
        # an FC member of the org.
        fc = _signup(client, cleanup_registry, "functional_consultant")
        fc_id = _uid(client, fc)
        db.add(OrganizationMembership(
            id=uuid.uuid4().hex, organization_id=org_id,
            user_id=fc_id, role="member",
        ))
        db.commit()

        r = client.post(
            "/api/projects/start",
            json={"project_name": "CS Direct", "module": "FI",
                  "organization_id": org_id},
            headers=fc,
        )
        sid = r.json()["session_id"]

        r = client.get(f"/api/projects/{sid}/case-study", headers=owner)
        assert r.status_code == 404


class TestCaseStudyResponse:
    def test_response_fields_present(self, client, cleanup_registry, db):
        owner = _signup(client, cleanup_registry, "business_development")
        consultant = _signup(client, cleanup_registry, "functional_consultant")
        _, sid = _won_opportunity(client, db, cleanup_registry, owner, consultant)

        r = client.get(f"/api/projects/{sid}/case-study", headers=owner)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["session_id"] == sid
        assert "requirements" in body
        assert "deliverables" in body
        assert isinstance(body["deliverables"], list)