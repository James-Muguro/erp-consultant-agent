"""
Grant-management tests (Phase 2.4 Q7 + Phase 2.6 status guards).

Snapshot basis: src/api/grants_api.py as seen in Phase 2.4; the
`require_project_grant_management` guard in src/auth/guards.py as seen
in Phase 2.4/2.6.

Coverage:
  * Personal-project owner can manage grants without PROJECT_GRANTS_MANAGE.
  * Capability holder can manage org-project grants if they are also a
    member.
  * Capability holder is denied (404) on unrelated personal projects.
  * Non-member is denied.
  * Grant to non-member -> 400.
  * Idempotent grant upsert (designation change in place).
  * Revoke idempotent.
  * History returns revoked rows.
  * Eligible ERP Users empty for personal project; lists org members
    with erp_user role for org projects.
  * Signatory flag rejected for non-FRD; participant flag rejected for
    non-UAT.
"""
from __future__ import annotations

import uuid
from typing import Dict

import pytest

from src.auth.project_access import ArtifactType, create_grant
from src.db.base import SessionLocal
from src.db.models import Organization, OrganizationMembership
from tests._auth_helpers import signup_and_authenticate
from tests.conftest import unique_email
from src.memory import agent_memory


def _signup(client, cleanup_registry, role: str) -> Dict[str, str]:
    email = unique_email(f"gm-{role}")
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


class TestGuardBehavior:
    def test_personal_owner_manages_grants_without_capability(
        self, client, cleanup_registry,
    ):
        """A personal-project owner without PROJECT_GRANTS_MANAGE can
        still manage grants on their own project. Project created
        directly because erp_user lacks PROJECT_CREATE."""
        headers = _signup(client, cleanup_registry, "erp_user")
        owner_id = _uid(client, headers)

        sid = agent_memory.create_project(
            project_name="GM Personal",
            module="FI",
            user_id=owner_id,
        )

        r = client.get(f"/api/projects/{sid}/grants", headers=headers)
        assert r.status_code == 200, r.text
        assert r.json() == {"grants": []}

    def test_non_owner_denied_on_personal_project(
        self, client, cleanup_registry,
    ):
        owner_headers = _signup(client, cleanup_registry, "erp_user")
        owner_id = _uid(client, owner_headers)
        sid = agent_memory.create_project(
            project_name="GM Personal Deny",
            module="FI",
            user_id=owner_id,
        )

        other = _signup(client, cleanup_registry, "functional_consultant")
        r = client.get(f"/api/projects/{sid}/grants", headers=other)
        assert r.status_code == 404

    def test_capability_holder_denied_on_unrelated_personal_project(
        self, client, cleanup_registry,
    ):
        owner_headers = _signup(client, cleanup_registry, "erp_user")
        owner_id = _uid(client, owner_headers)
        sid = agent_memory.create_project(
            project_name="GM Personal Foreign",
            module="FI",
            user_id=owner_id,
        )

        fc = _signup(client, cleanup_registry, "functional_consultant")
        r = client.get(f"/api/projects/{sid}/grants", headers=fc)
        assert r.status_code == 404


class TestEligibleUsers:
    def test_eligible_empty_for_personal_project(
        self, client, auth_headers,
    ):
        sid = _start(client, auth_headers, "GM Eligible Personal")
        r = client.get(
            f"/api/projects/{sid}/grants/eligible-erp-users",
            headers=auth_headers,
        )
        assert r.status_code == 200
        assert r.json() == {"users": []}

    def test_eligible_lists_org_erp_users(
        self, client, auth_headers, db, cleanup_registry,
    ):
        owner_id = _uid(client, auth_headers)
        erp_headers = _signup(client, cleanup_registry, "erp_user")
        erp_id = _uid(client, erp_headers)
        # FC in the same org who is NOT an erp_user should not appear.
        fc_headers = _signup(client, cleanup_registry, "functional_consultant")
        fc_id = _uid(client, fc_headers)

        org_id = _org_with_members(db, owner_id, [erp_id, fc_id], "GM Eligible Org")
        cleanup_registry.org_ids.append(org_id)
        sid = _start(client, auth_headers, "GM Eligible Proj", org_id)

        r = client.get(
            f"/api/projects/{sid}/grants/eligible-erp-users",
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        ids = {u["user_id"] for u in r.json()["users"]}
        assert erp_id in ids
        assert fc_id not in ids


class TestGrantLifecycle:
    def test_grant_to_non_member_returns_400(
        self, client, auth_headers, db, cleanup_registry,
    ):
        owner_id = _uid(client, auth_headers)
        outsider = _signup(client, cleanup_registry, "erp_user")
        outsider_id = _uid(client, outsider)
        org_id = _org_with_members(db, owner_id, [], "GM Nonmember Org")
        cleanup_registry.org_ids.append(org_id)
        sid = _start(client, auth_headers, "GM Nonmember Proj", org_id)

        r = client.post(
            f"/api/projects/{sid}/grants",
            json={"user_id": outsider_id, "artifact_type": "frd"},
            headers=auth_headers,
        )
        assert r.status_code == 400

    def test_grant_upsert_updates_designation_in_place(
        self, client, auth_headers, db, cleanup_registry,
    ):
        owner_id = _uid(client, auth_headers)
        erp_headers = _signup(client, cleanup_registry, "erp_user")
        erp_id = _uid(client, erp_headers)
        org_id = _org_with_members(db, owner_id, [erp_id], "GM Upsert Org")
        cleanup_registry.org_ids.append(org_id)
        sid = _start(client, auth_headers, "GM Upsert Proj", org_id)

        r1 = client.post(
            f"/api/projects/{sid}/grants",
            json={"user_id": erp_id, "artifact_type": "frd", "is_signatory": False},
            headers=auth_headers,
        )
        assert r1.status_code == 200, r1.text
        g1 = r1.json()
        assert g1["is_signatory"] is False

        r2 = client.post(
            f"/api/projects/{sid}/grants",
            json={"user_id": erp_id, "artifact_type": "frd", "is_signatory": True},
            headers=auth_headers,
        )
        assert r2.status_code == 200, r2.text
        g2 = r2.json()
        assert g2["is_signatory"] is True
        assert g2["id"] == g1["id"]  # same row, updated in place

    def test_revoke_idempotent(self, client, auth_headers, db, cleanup_registry):
        owner_id = _uid(client, auth_headers)
        erp_headers = _signup(client, cleanup_registry, "erp_user")
        erp_id = _uid(client, erp_headers)
        org_id = _org_with_members(db, owner_id, [erp_id], "GM Revoke Org")
        cleanup_registry.org_ids.append(org_id)
        sid = _start(client, auth_headers, "GM Revoke Proj", org_id)

        create_grant(
            db, session_id=sid, grantee_user_id=erp_id,
            artifact_type=ArtifactType.UAT_SCENARIOS,
            granted_by_user_id=owner_id,
        )
        db.commit()

        r1 = client.delete(
            f"/api/projects/{sid}/grants/{erp_id}/uat_scenarios",
            headers=auth_headers,
        )
        assert r1.status_code == 200
        assert r1.json() == {"revoked": True}

        r2 = client.delete(
            f"/api/projects/{sid}/grants/{erp_id}/uat_scenarios",
            headers=auth_headers,
        )
        assert r2.status_code == 200
        assert r2.json() == {"revoked": False}

    def test_history_returns_revoked_rows_with_attribution(
        self, client, auth_headers, db, cleanup_registry,
    ):
        owner_id = _uid(client, auth_headers)
        erp_headers = _signup(client, cleanup_registry, "erp_user")
        erp_id = _uid(client, erp_headers)
        org_id = _org_with_members(db, owner_id, [erp_id], "GM Hist Org")
        cleanup_registry.org_ids.append(org_id)
        sid = _start(client, auth_headers, "GM Hist Proj", org_id)

        create_grant(
            db, session_id=sid, grantee_user_id=erp_id,
            artifact_type=ArtifactType.TRAINING_MATERIALS,
            granted_by_user_id=owner_id,
        )
        db.commit()
        client.delete(
            f"/api/projects/{sid}/grants/{erp_id}/training_materials",
            headers=auth_headers,
        )

        r = client.get(f"/api/projects/{sid}/grants/history", headers=auth_headers)
        assert r.status_code == 200
        rows = r.json()["grants"]
        assert len(rows) == 1
        assert rows[0]["user_id"] == erp_id
        assert rows[0]["revoked_at"] is not None
        assert rows[0]["revoked_by_user_id"] == owner_id


class TestDesignationIncoherence:
    def test_signatory_rejected_for_non_frd(
        self, client, auth_headers, db, cleanup_registry,
    ):
        owner_id = _uid(client, auth_headers)
        erp_headers = _signup(client, cleanup_registry, "erp_user")
        erp_id = _uid(client, erp_headers)
        org_id = _org_with_members(db, owner_id, [erp_id], "GM Incoh Org")
        cleanup_registry.org_ids.append(org_id)
        sid = _start(client, auth_headers, "GM Incoh Proj", org_id)

        r = client.post(
            f"/api/projects/{sid}/grants",
            json={
                "user_id": erp_id,
                "artifact_type": "uat_scenarios",
                "is_signatory": True,
            },
            headers=auth_headers,
        )
        assert r.status_code == 400

    def test_uat_participant_rejected_for_non_uat(
        self, client, auth_headers, db, cleanup_registry,
    ):
        owner_id = _uid(client, auth_headers)
        erp_headers = _signup(client, cleanup_registry, "erp_user")
        erp_id = _uid(client, erp_headers)
        org_id = _org_with_members(db, owner_id, [erp_id], "GM Incoh2 Org")
        cleanup_registry.org_ids.append(org_id)
        sid = _start(client, auth_headers, "GM Incoh2 Proj", org_id)

        r = client.post(
            f"/api/projects/{sid}/grants",
            json={
                "user_id": erp_id,
                "artifact_type": "frd",
                "is_uat_participant": True,
            },
            headers=auth_headers,
        )
        assert r.status_code == 400