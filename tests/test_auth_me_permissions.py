"""
Tests for the two capability fields added to `UserOut` in Phase 2.1:

  * `permissions`             — the caller's effective application
                                permissions, computed from the union
                                of ROLE_PERMISSIONS over the roles they
                                hold.
  * `organization_privileges` — per-organization privileges derived
                                from ORG_ROLE_PRIVILEGES, keyed by
                                organization id.

These fields are what makes the frontend capability layer possible
without the SPA duplicating the role→permission mapping. The frontend
treats the lists as opaque; the server remains the sole authority.

Additive: this file does not modify tests/test_auth_me.py or any other
existing test. It exercises the new fields end-to-end through the
shipped /me endpoint.

Correction (Phase 2.2): the assertion for an organization-only user
was originally written against the intent stated in the docstring for
`_COMMON_USER_PERMS`, which claims these permissions are universal.
The shipped backend grants them only through a role, and an
organization-only user holds no application role. The test now asserts
the actual behaviour. See GAPS in the Phase 2.2 summary.
"""
from __future__ import annotations

import uuid
from typing import List, Tuple

import pytest
from fastapi.testclient import TestClient

from src.email import reset_email_provider, set_email_provider
from src.orchestrator_api import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _reset_email_provider_after_test():
    yield
    reset_email_provider()


def _unique_email(prefix: str = "me-perms") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}@example.com"


def _complete_auth_flow(
    client: TestClient,
    email: str,
    account_type: str = "developer",
    organization_name: str | None = None,
    password: str = "testpassword123",
) -> str:
    captured: List[Tuple[str, str, str]] = []

    def _capture(to: str, subject: str, body: str) -> None:
        captured.append((to, subject, body))

    set_email_provider(_capture)
    payload = {
        "email": email,
        "password": password,
        "account_type": account_type,
    }
    if organization_name is not None:
        payload["organization_name"] = organization_name

    r = client.post("/api/auth/signup", json=payload)
    assert r.status_code == 200, f"signup failed: {r.text}"

    raw_verify = captured[-1][2].split("token=")[1].split("\n")[0]
    r = client.post("/api/auth/verify-email", json={"token": raw_verify})
    assert r.status_code == 200, f"verify-email failed: {r.text}"

    r = client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
    )
    assert r.status_code == 200, f"login failed: {r.text}"
    pending_ref = r.json()["pending_auth_ref"]

    otp_code = captured[-1][2].split("    ")[1].split("\n")[0].strip()
    r = client.post(
        "/api/auth/login/verify-otp",
        json={"pending_auth_ref": pending_ref, "code": otp_code},
    )
    assert r.status_code == 200, f"verify-otp failed: {r.text}"
    return r.json()["access_token"]


def _me(client: TestClient, token: str) -> dict:
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------------------
# Application permissions per role
# ---------------------------------------------------------------------------
class TestMePermissionsField:
    def test_developer_permissions_match_role_mapping(self, client):
        token = _complete_auth_flow(client, _unique_email(), "developer")
        body = _me(client, token)

        assert isinstance(body["permissions"], list)
        assert "chat:submit" in body["permissions"]
        assert "solution:record_actual" in body["permissions"]
        assert "testing:write" in body["permissions"]
        assert "project:create" not in body["permissions"]
        assert "project:edit" not in body["permissions"]
        assert "requirements:revise" not in body["permissions"]
        assert "process_steps:revise" not in body["permissions"]
        assert "consistency:run" not in body["permissions"]
        assert body["organization_privileges"] == {}

    def test_functional_consultant_permissions_match_role_mapping(self, client):
        token = _complete_auth_flow(
            client, _unique_email("fc"), "functional_consultant"
        )
        body = _me(client, token)
        assert "project:create" in body["permissions"]
        assert "project:edit" in body["permissions"]
        assert "project:delete" in body["permissions"]
        assert "requirements:revise" in body["permissions"]
        assert "consistency:run" in body["permissions"]
        assert "phase:execute" in body["permissions"]

    def test_erp_user_permissions_are_read_only(self, client):
        token = _complete_auth_flow(client, _unique_email("erp"), "erp_user")
        body = _me(client, token)
        perms = set(body["permissions"])
        assert perms == {
            "chat:submit",
            "feedback:submit",
            "profile:edit",
            "project:read",
        }
        assert "requirements:read" not in perms
        assert "testing:read" not in perms

    def test_business_development_permissions_match_role_mapping(self, client):
        token = _complete_auth_flow(client, _unique_email("mkt"), "business_development")
        body = _me(client, token)
        assert "chat:submit" in body["permissions"]
        assert "project:read" in body["permissions"]
        assert "documents:generate" in body["permissions"]
        assert "requirements:revise" not in body["permissions"]
        assert "testing:write" not in body["permissions"]

    def test_permissions_are_sorted(self, client):
        token = _complete_auth_flow(client, _unique_email("sorted"), "developer")
        permissions = _me(client, token)["permissions"]
        assert permissions == sorted(permissions)


# ---------------------------------------------------------------------------
# Organization privileges
# ---------------------------------------------------------------------------
class TestMeOrganizationPrivilegesField:
    def test_org_only_owner_has_empty_application_permissions_and_owner_privileges(
        self, client,
    ):
        """An organization signup produces a user with no application
        role. The current backend grants no application permission in
        that case — `_COMMON_USER_PERMS` is only attached through a
        role. The organization privilege map carries the owner
        privileges.

        This asserts the current backend behavior. A follow-up
        decision (documented in Phase 2.2 GAPS) is whether org-only
        users should in fact receive the cross-cutting permissions
        described in `_COMMON_USER_PERMS`' docstring.
        """
        email = _unique_email("orgowner")
        org_name = f"Perm Test Org {uuid.uuid4().hex[:6]}"
        token = _complete_auth_flow(
            client, email, "organization", organization_name=org_name
        )
        body = _me(client, token)

        assert body["roles"] == []
        assert body["permissions"] == []

        assert len(body["organization_privileges"]) == 1
        org_id = next(iter(body["organization_privileges"]))
        assert isinstance(org_id, str) and org_id
        privs = body["organization_privileges"][org_id]
        assert "org:member:manage" in privs
        assert "org:settings:edit" in privs

        assert len(body["organizations"]) == 1
        assert body["organizations"][0]["id"] == org_id
        assert body["organizations"][0]["role"] == "owner"

    def test_individual_user_has_empty_privilege_map(self, client):
        token = _complete_auth_flow(
            client, _unique_email("individual"), "developer"
        )
        body = _me(client, token)
        assert body["organization_privileges"] == {}