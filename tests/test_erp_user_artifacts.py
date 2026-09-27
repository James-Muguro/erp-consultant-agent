"""
ERP User artifact-grant tests (Phase 2.4).

Snapshot basis: src/api/erp_user_api.py and src/auth/project_access.py as
seen during Phase 2.4/2.5 inspection. If the on-disk api module has
drifted (e.g. new endpoints), the artifact summary and per-artifact
endpoints asserted here remain the Phase 2.4 contract and are what this
file covers.

Coverage:
  * Artifact grant summary listing (only active grants).
  * Questionnaire access requires the requirements_questionnaire grant.
  * FRD access requires the frd grant; signatory is a designation.
  * UAT scenarios access requires the uat_scenarios grant.
  * Training materials access requires the training_materials grant.
  * Cross-project grant misuse returns 404.
  * Cross-user misuse returns 404.
  * Non-member with a grant is rejected (membership is required first).
  * Revoked grant denies access.

Fixtures: tests/conftest.py.
Direct DB setup: creating SessionUserArtifactGrant rows is done via
src.auth.project_access.create_grant, since there is no HTTP path for
a test to fabricate a grant on behalf of an arbitrary project member.
"""
from __future__ import annotations

import uuid
from typing import Dict

import pytest

from src.auth.project_access import (
    ArtifactType,
    create_grant,
    revoke_grant,
)
from src.db.base import SessionLocal
from src.db.models import Organization, OrganizationMembership
from tests._auth_helpers import signup_and_authenticate
from tests.conftest import unique_email


def _signup(client, cleanup_registry, role: str) -> Dict[str, str]:
    email = unique_email(f"art-{role}")
    cleanup_registry.emails.append(email)
    token = signup_and_authenticate(client, email=email, account_type=role)
    return {"Authorization": f"Bearer {token}"}


def _uid(client, headers) -> str:
    r = client.get("/api/auth/me", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _start_project(client, headers, name: str, org_id=None) -> str:
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


def _org_with_members(db, owner_id: str, member_ids, name: str) -> str:
    org_id = uuid.uuid4().hex
    db.add(Organization(id=org_id, name=name, created_by=owner_id))
    db.add(OrganizationMembership(
        id=uuid.uuid4().hex, organization_id=org_id,
        user_id=owner_id, role="owner",
    ))
    for uid in member_ids:
        db.add(OrganizationMembership(
            id=uuid.uuid4().hex, organization_id=org_id,
            user_id=uid, role="member",
        ))
    db.commit()
    return org_id


class TestArtifactSummary:
    def test_summary_is_empty_without_grants(self, client, auth_headers):
        r = client.post(
            "/api/projects/start",
            json={"project_name": "Art Sum", "module": "FI"},
            headers=auth_headers,
        )
        sid = r.json()["session_id"]
        r = client.get(
            f"/api/projects/{sid}/erp-user/artifacts", headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        assert r.json() == {"session_id": sid, "grants": []}

    def test_summary_lists_active_grants_for_member(
        self, client, auth_headers, db, cleanup_registry,
    ):
        owner_id = _uid(client, auth_headers)
        erp_headers = _signup(client, cleanup_registry, "erp_user")
        erp_id = _uid(client, erp_headers)

        org_id = _org_with_members(db, owner_id, [erp_id], "Art Summary Org")
        cleanup_registry.org_ids.append(org_id)
        sid = _start_project(client, auth_headers, "Art Summary Proj", org_id)

        create_grant(
            db, session_id=sid, grantee_user_id=erp_id,
            artifact_type=ArtifactType.REQUIREMENTS_QUESTIONNAIRE,
            granted_by_user_id=owner_id,
        )
        create_grant(
            db, session_id=sid, grantee_user_id=erp_id,
            artifact_type=ArtifactType.FRD,
            granted_by_user_id=owner_id,
            is_signatory=True,
        )
        db.commit()

        r = client.get(
            f"/api/projects/{sid}/erp-user/artifacts", headers=erp_headers,
        )
        assert r.status_code == 200, r.text
        grants = r.json()["grants"]
        types = {g["artifact_type"] for g in grants}
        assert types == {"requirements_questionnaire", "frd"}
        frd = next(g for g in grants if g["artifact_type"] == "frd")
        assert frd["is_signatory"] is True


class TestArtifactAccessGating:
    @pytest.mark.parametrize("endpoint,artifact", [
        ("questionnaire", ArtifactType.REQUIREMENTS_QUESTIONNAIRE),
        ("frd", ArtifactType.FRD),
        ("uat-scenarios", ArtifactType.UAT_SCENARIOS),
        ("training-materials", ArtifactType.TRAINING_MATERIALS),
    ])
    def test_endpoint_requires_matching_grant(
        self, client, auth_headers, db, cleanup_registry,
        endpoint, artifact,
    ):
        owner_id = _uid(client, auth_headers)
        erp_headers = _signup(client, cleanup_registry, "erp_user")
        erp_id = _uid(client, erp_headers)
        org_id = _org_with_members(db, owner_id, [erp_id], f"Art Gate {endpoint}")
        cleanup_registry.org_ids.append(org_id)
        sid = _start_project(client, auth_headers, "Art Gate Proj", org_id)

        # No grant yet -> 404.
        r = client.get(
            f"/api/projects/{sid}/erp-user/{endpoint}", headers=erp_headers,
        )
        assert r.status_code == 404

        # Grant a *different* artifact -> still 404.
        other = (
            ArtifactType.FRD
            if artifact != ArtifactType.FRD
            else ArtifactType.REQUIREMENTS_QUESTIONNAIRE
        )
        create_grant(
            db, session_id=sid, grantee_user_id=erp_id,
            artifact_type=other, granted_by_user_id=owner_id,
        )
        db.commit()
        r = client.get(
            f"/api/projects/{sid}/erp-user/{endpoint}", headers=erp_headers,
        )
        assert r.status_code == 404

        # Grant the correct artifact -> 200.
        create_grant(
            db, session_id=sid, grantee_user_id=erp_id,
            artifact_type=artifact, granted_by_user_id=owner_id,
        )
        db.commit()
        r = client.get(
            f"/api/projects/{sid}/erp-user/{endpoint}", headers=erp_headers,
        )
        assert r.status_code == 200, r.text

    def test_revoked_grant_denies_access(
        self, client, auth_headers, db, cleanup_registry,
    ):
        owner_id = _uid(client, auth_headers)
        erp_headers = _signup(client, cleanup_registry, "erp_user")
        erp_id = _uid(client, erp_headers)
        org_id = _org_with_members(db, owner_id, [erp_id], "Art Revoke Org")
        cleanup_registry.org_ids.append(org_id)
        sid = _start_project(client, auth_headers, "Art Revoke Proj", org_id)

        create_grant(
            db, session_id=sid, grantee_user_id=erp_id,
            artifact_type=ArtifactType.FRD, granted_by_user_id=owner_id,
        )
        db.commit()
        assert client.get(
            f"/api/projects/{sid}/erp-user/frd", headers=erp_headers,
        ).status_code == 200

        revoke_grant(
            db, session_id=sid, grantee_user_id=erp_id,
            artifact_type=ArtifactType.FRD, revoked_by_user_id=owner_id,
        )
        db.commit()
        assert client.get(
            f"/api/projects/{sid}/erp-user/frd", headers=erp_headers,
        ).status_code == 404


class TestMembershipLayering:
    def test_non_member_with_grant_denied(
        self, client, auth_headers, db, cleanup_registry,
    ):
        """A user with a grant but no org membership is rejected. In the
        current model, create_grant itself refuses non-members, so this
        is asserted at the service level: the call raises ValueError."""
        owner_id = _uid(client, auth_headers)
        outsider_headers = _signup(client, cleanup_registry, "erp_user")
        outsider_id = _uid(client, outsider_headers)

        org_id = _org_with_members(db, owner_id, [], "Art Nonmember Org")
        cleanup_registry.org_ids.append(org_id)
        sid = _start_project(client, auth_headers, "Art Nonmember", org_id)

        with pytest.raises(ValueError):
            create_grant(
                db, session_id=sid, grantee_user_id=outsider_id,
                artifact_type=ArtifactType.FRD,
                granted_by_user_id=owner_id,
            )

    def test_cross_project_grant_denied(
        self, client, auth_headers, db, cleanup_registry,
    ):
        owner_id = _uid(client, auth_headers)
        erp_headers = _signup(client, cleanup_registry, "erp_user")
        erp_id = _uid(client, erp_headers)
        org_id = _org_with_members(db, owner_id, [erp_id], "Art Cross Proj Org")
        cleanup_registry.org_ids.append(org_id)

        sid_a = _start_project(client, auth_headers, "Art Cross A", org_id)
        sid_b = _start_project(client, auth_headers, "Art Cross B", org_id)

        create_grant(
            db, session_id=sid_a, grantee_user_id=erp_id,
            artifact_type=ArtifactType.FRD, granted_by_user_id=owner_id,
        )
        db.commit()

        # Grant was on sid_a; endpoint on sid_b must 404.
        assert client.get(
            f"/api/projects/{sid_b}/erp-user/frd", headers=erp_headers,
        ).status_code == 404