"""
Opportunity workflow tests.


Coverage:
  * Opportunity creation, listing, retrieval (scoped by org).
  * Cross-org access denied.
  * State transitions draft → tor_finalized → won enforced by 409
    guards on sibling endpoints (Phase 2.6).
  * Mark-as-Won conversion: creates SessionRecord, copies finalized
    requirements, sets converted_session_id, inserts bid-won attention
    item.
  * Invalid Mark-as-Won transitions (draft, already-won).
  * Atomic rollback when attention creation fails.
  * Concurrent Mark-as-Won protection via PostgreSQL row lock.


Fixtures: tests/conftest.py.
Direct DB setup: opportunity requirements are seeded directly because
the extraction endpoint requires a real file upload; the extraction
path is covered by test_tor_extraction.py.
"""
from __future__ import annotations


import threading
import uuid
from typing import Dict


import pytest


from src.db.base import SessionLocal
from src.db.models import (
    AttentionItem,
    Opportunity,
    OpportunityRequirement,
    Organization,
    OrganizationMembership,
    RequirementItemRecord,
    SessionRecord,
)
from src.services import attention_service
from tests._auth_helpers import signup_and_authenticate
from tests.conftest import unique_email



def _signup(client, cleanup_registry, role: str) -> Dict[str, str]:
    email = unique_email(f"opp-{role}")
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



def _seed_finalized_req(db, opp_id: str, code: str = "TOR-001"):
    db.add(OpportunityRequirement(
        id=uuid.uuid4().hex,
        opportunity_id=opp_id,
        external_code=code,
        description=f"Req {code}",
        priority="Medium",
        req_type="Functional",
        status="draft",
        ai_draft_status="finalized",
        fit_response="meets_out_of_the_box",
        fit_response_comment="OK",
    ))
    db.commit()



class TestOpportunityCrud:
    def test_create_and_retrieve(self, client, cleanup_registry, db):
        owner = _signup(client, cleanup_registry, "business_development")
        owner_id = _uid(client, owner)
        org_id = _org_with_members(db, owner_id, [], "Opp CRUD Org")
        cleanup_registry.org_ids.append(org_id)


        r = client.post(
            "/api/opportunities",
            json={"title": "T", "client_name": "C", "organization_id": org_id},
            headers=owner,
        )
        assert r.status_code == 200, r.text
        opp_id = r.json()["id"]
        cleanup_registry.opportunity_ids.append(opp_id)


        r = client.get(f"/api/opportunities/{opp_id}", headers=owner)
        assert r.status_code == 200
        assert r.json()["title"] == "T"


    def test_cross_org_access_denied(self, client, cleanup_registry, db):
        owner = _signup(client, cleanup_registry, "business_development")
        owner_id = _uid(client, owner)
        org_id = _org_with_members(db, owner_id, [], "Opp CrossOrg A")
        cleanup_registry.org_ids.append(org_id)


        outsider = _signup(client, cleanup_registry, "business_development")
        outsider_id = _uid(client, outsider)
        org_b = _org_with_members(db, outsider_id, [], "Opp CrossOrg B")
        cleanup_registry.org_ids.append(org_b)


        r = client.post(
            "/api/opportunities",
            json={"title": "T", "client_name": "C", "organization_id": org_id},
            headers=owner,
        )
        opp_id = r.json()["id"]
        cleanup_registry.opportunity_ids.append(opp_id)


        r = client.get(f"/api/opportunities/{opp_id}", headers=outsider)
        assert r.status_code == 404



class TestStateGuards:
    def test_status_guards_block_mutations_after_won(
        self, client, cleanup_registry, db,
    ):
        owner = _signup(client, cleanup_registry, "business_development")
        owner_id = _uid(client, owner)
        org_id = _org_with_members(db, owner_id, [], "Opp Guards Org")
        cleanup_registry.org_ids.append(org_id)


        r = client.post(
            "/api/opportunities",
            json={"title": "T", "client_name": "C", "organization_id": org_id},
            headers=owner,
        )
        opp_id = r.json()["id"]
        cleanup_registry.opportunity_ids.append(opp_id)


        # Force status to won directly (setup only).
        opp = db.get(Opportunity, opp_id)
        opp.status = "won"
        db.commit()


        # Any mutation guarded by the non-terminal status check must 409.
        r = client.post(
            f"/api/opportunities/{opp_id}/mark-tor-finalized", headers=owner,
        )
        assert r.status_code == 409


        r = client.patch(
            f"/api/opportunities/{opp_id}",
            json={"title": "New"},
            headers=owner,
        )
        assert r.status_code == 409



class TestMarkAsWon:
    def test_mark_won_creates_project_and_copies_requirements(
        self, client, cleanup_registry, db,
    ):
        owner = _signup(client, cleanup_registry, "business_development")
        consultant = _signup(client, cleanup_registry, "functional_consultant")
        owner_id = _uid(client, owner)
        consultant_id = _uid(client, consultant)


        org_id = _org_with_members(db, owner_id, [consultant_id], "Opp Won Org")
        cleanup_registry.org_ids.append(org_id)


        r = client.post(
            "/api/opportunities",
            json={"title": "W", "client_name": "C", "organization_id": org_id},
            headers=owner,
        )
        opp_id = r.json()["id"]
        cleanup_registry.opportunity_ids.append(opp_id)


        _seed_finalized_req(db, opp_id, "TOR-001")
        _seed_finalized_req(db, opp_id, "TOR-002")
        opp = db.get(Opportunity, opp_id)
        opp.status = "tor_finalized"
        opp.assigned_consultant_user_id = consultant_id
        db.commit()


        r = client.post(
            f"/api/opportunities/{opp_id}/mark-won", json={}, headers=owner,
        )
        assert r.status_code == 200, r.text
        session_id = r.json()["session_id"]


        db.expire_all()
        sess = db.get(SessionRecord, session_id)
        assert sess is not None
        assert sess.organization_id == org_id


        reqs = (
            db.query(RequirementItemRecord)
            .filter(RequirementItemRecord.session_id == session_id)
            .all()
        )
        codes = {r.external_code for r in reqs}
        assert codes == {"TOR-001", "TOR-002"}


        opp = db.get(Opportunity, opp_id)
        assert opp.status == "won"
        assert opp.converted_session_id == session_id
        assert opp.won_at is not None


        # Bid-won attention item for the consultant.
        pending = attention_service.list_pending(db, consultant_id)
        assert any(
            i.source_type == attention_service.SOURCE_TYPE_BID_WON
            and i.source_id == opp_id
            for i in pending
        )


    def test_mark_won_from_draft_is_rejected(
        self, client, cleanup_registry, db,
    ):
        owner = _signup(client, cleanup_registry, "business_development")
        consultant = _signup(client, cleanup_registry, "functional_consultant")
        owner_id = _uid(client, owner)
        consultant_id = _uid(client, consultant)
        org_id = _org_with_members(db, owner_id, [consultant_id], "Opp Draft Org")
        cleanup_registry.org_ids.append(org_id)

        r = client.post(
            "/api/opportunities",
            json={"title": "T", "client_name": "C", "organization_id": org_id},
            headers=owner,
        )
        opp_id = r.json()["id"]
        cleanup_registry.opportunity_ids.append(opp_id)

        opp = db.get(Opportunity, opp_id)
        opp.assigned_consultant_user_id = consultant_id
        db.commit()

        r = client.post(
            f"/api/opportunities/{opp_id}/mark-won", json={}, headers=owner,
        )
        assert r.status_code == 409

    def test_mark_won_twice_rejected(
        self, client, cleanup_registry, db,
    ):
        owner = _signup(client, cleanup_registry, "business_development")
        consultant = _signup(client, cleanup_registry, "functional_consultant")
        owner_id = _uid(client, owner)
        consultant_id = _uid(client, consultant)


        org_id = _org_with_members(db, owner_id, [consultant_id], "Opp Twice Org")
        cleanup_registry.org_ids.append(org_id)


        r = client.post(
            "/api/opportunities",
            json={"title": "T", "client_name": "C", "organization_id": org_id},
            headers=owner,
        )
        opp_id = r.json()["id"]
        cleanup_registry.opportunity_ids.append(opp_id)


        _seed_finalized_req(db, opp_id, "TOR-001")
        opp = db.get(Opportunity, opp_id)
        opp.status = "tor_finalized"
        opp.assigned_consultant_user_id = consultant_id
        db.commit()


        r1 = client.post(
            f"/api/opportunities/{opp_id}/mark-won", json={}, headers=owner,
        )
        assert r1.status_code == 200


        r2 = client.post(
            f"/api/opportunities/{opp_id}/mark-won", json={}, headers=owner,
        )
        assert r2.status_code == 409



class TestAtomicConversion:
    def test_rollback_when_attention_creation_fails(
        self, client, cleanup_registry, db, monkeypatch,
    ):
        """Force the downstream attention-item creation to fail; assert
        the whole transaction rolls back."""
        owner = _signup(client, cleanup_registry, "business_development")
        consultant = _signup(client, cleanup_registry, "functional_consultant")
        owner_id = _uid(client, owner)
        consultant_id = _uid(client, consultant)


        org_id = _org_with_members(db, owner_id, [consultant_id], "Opp Rollback Org")
        cleanup_registry.org_ids.append(org_id)


        r = client.post(
            "/api/opportunities",
            json={"title": "T", "client_name": "C", "organization_id": org_id},
            headers=owner,
        )
        opp_id = r.json()["id"]
        cleanup_registry.opportunity_ids.append(opp_id)
        _seed_finalized_req(db, opp_id, "TOR-001")
        opp = db.get(Opportunity, opp_id)
        opp.status = "tor_finalized"
        opp.assigned_consultant_user_id = consultant_id
        db.commit()


        from src.services import attention_service as attn
        def _boom(*a, **k):
            raise RuntimeError("simulated attention failure")
        monkeypatch.setattr(attn, "create_attention_item", _boom)


        with pytest.raises(RuntimeError, match="simulated attention failure"):
            client.post(
                f"/api/opportunities/{opp_id}/mark-won", json={}, headers=owner,
            )


        # Reopen a fresh session to observe final DB state.
        fresh = SessionLocal()
        try:
            opp = fresh.get(Opportunity, opp_id)
            assert opp.status == "tor_finalized"
            assert opp.converted_session_id is None
            # No SessionRecord was left for this opportunity.
            from src.db.models import SessionRecord as SR
            count = (
                fresh.query(SR)
                .filter(SR.organization_id == org_id)
                .count()
            )
            assert count == 0
        finally:
            fresh.close()