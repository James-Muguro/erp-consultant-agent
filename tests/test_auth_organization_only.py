"""
Integration tests for the organization-only user experience.

A user who signed up with account_type='organization' has:
  * exactly one Organization (created at signup),
  * exactly one OrganizationMembership with role='owner' for that
    organization,
  * zero UserRoleRecord rows.

Consequences exercised by this file:

  * The user can complete the full auth flow (signup → verify-email →
    login → verify-otp); authentication is independent of the
    application-role grants.
  * /api/auth/me returns roles: [] and the owner organization.
  * Every currently-guarded route that requires an application-role
    permission returns 403 for this user, because the user holds no
    application role and therefore no permissions.

Routes covered:
  * GET  /api/projects        — requires PROJECT_READ
  * POST /api/chat            — requires CHAT_SUBMIT
  * POST /api/projects/start  — requires PROJECT_CREATE

Design notes:
  * TestClient is entered as a context manager so the FastAPI lifespan
    runs.

  * The full auth flow is used to obtain an access token. The email
    abstraction is mocked for the duration of the flow, matching the
    pattern used by tests/test_auth_lifecycle.py.

  * The 403 assertions deliberately choose routes whose permission
    guard runs on the dependency layer, before the route body.

  * The user's organization and membership are not cleaned up
    explicitly by this file. The created_users fixture deletes
    organizations created_by the tracked users first (memberships
    cascade via organization_memberships.organization_id ON DELETE
    CASCADE), then deletes the users.

  * No production code, existing test file, fixture, migration, or
    product capability is modified by this file.
"""
from __future__ import annotations

import uuid
from contextlib import contextmanager
from typing import Iterator, List, Tuple

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.db.base import SessionLocal
from src.db.models import Organization, User
from src.email import reset_email_provider, set_email_provider
from src.orchestrator_api import app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
@contextmanager
def _db_session() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _unique_email() -> str:
    return f"org-only-test-{uuid.uuid4().hex[:12]}@example.com"


_PASSWORD = "testpassword123"


def _signup_organization_and_authenticate(
    client: TestClient,
    email: str,
    org_name: str,
) -> str:
    """Complete the full flow for an organization signup and return the
    access token issued by /api/auth/login/verify-otp."""
    captured: List[Tuple[str, str, str]] = []

    def _capture(to: str, subject: str, body: str) -> None:
        captured.append((to, subject, body))

    set_email_provider(_capture)
    try:
        r = client.post(
            "/api/auth/signup",
            json={
                "email": email,
                "password": _PASSWORD,
                "account_type": "organization",
                "organization_name": org_name,
            },
        )
        assert r.status_code == 200, f"signup failed: {r.text}"

        verify_body = captured[-1][2]
        raw_verify = verify_body.split("token=")[1].split("\n")[0]
        r = client.post(
            "/api/auth/verify-email", json={"token": raw_verify}
        )
        assert r.status_code == 200, f"verify-email failed: {r.text}"

        r = client.post(
            "/api/auth/login",
            json={"email": email, "password": _PASSWORD},
        )
        assert r.status_code == 200, f"login failed: {r.text}"
        pending_ref = r.json()["pending_auth_ref"]

        otp_body = captured[-1][2]
        otp_code = otp_body.split("    ")[1].split("\n")[0].strip()

        r = client.post(
            "/api/auth/login/verify-otp",
            json={"pending_auth_ref": pending_ref, "code": otp_code},
        )
        assert r.status_code == 200, f"verify-otp failed: {r.text}"
        return r.json()["access_token"]
    finally:
        reset_email_provider()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _reset_email_provider_after_test():
    yield
    reset_email_provider()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def created_users():
    emails: List[str] = []
    yield emails
    if not emails:
        return
    lowered = [e.lower() for e in emails]
    with _db_session() as db:
        user_rows = db.query(User).filter(User.email.in_(lowered)).all()
        if not user_rows:
            return
        user_ids = [u.id for u in user_rows]

        db.query(Organization).filter(
            Organization.created_by.in_(user_ids)
        ).delete(synchronize_session=False)

        db.query(User).filter(
            User.id.in_(user_ids)
        ).delete(synchronize_session=False)

        db.commit()


@pytest.fixture
def org_only_user(client, created_users):
    """Sign up an organization-only user via the full auth flow and
    return the credentials and access token.

    Returns a dict with:
      email           the unique email used
      password        the password used
      org_name        the organization name supplied at signup
      access_token    the token issued by verify-otp
    """
    email = _unique_email()
    created_users.append(email)
    org_name = f"Org Only Test {uuid.uuid4().hex[:6]}"
    token = _signup_organization_and_authenticate(client, email, org_name)
    return {
        "email": email,
        "password": _PASSWORD,
        "org_name": org_name,
        "access_token": token,
    }


# ---------------------------------------------------------------------------
# Login (contract check)
# ---------------------------------------------------------------------------
class TestOrganizationOnlyLogin:
    def test_can_complete_login_after_signup(self, client, org_only_user):
        """An org-only user can complete the full auth flow. The token
        returned by the fixture is used here to reach /me, proving the
        flow produced a real bearer credential."""
        r = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {org_only_user['access_token']}"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["email"] == org_only_user["email"]

    def test_login_response_is_pending_auth_ref_not_token(
        self, client, created_users,
    ):
        """Explicitly check the login endpoint's shape for an org-only
        user: it returns a pending_auth_ref, not an access token."""
        email = _unique_email()
        created_users.append(email)
        org_name = f"Pending Ref Test {uuid.uuid4().hex[:6]}"

        captured: List[Tuple[str, str, str]] = []
        set_email_provider(lambda t, s, b: captured.append((t, s, b)))
        try:
            r = client.post(
                "/api/auth/signup",
                json={
                    "email": email,
                    "password": _PASSWORD,
                    "account_type": "organization",
                    "organization_name": org_name,
                },
            )
            assert r.status_code == 200
            raw_verify = (
                captured[-1][2].split("token=")[1].split("\n")[0]
            )
            client.post(
                "/api/auth/verify-email", json={"token": raw_verify}
            )

            r = client.post(
                "/api/auth/login",
                json={"email": email, "password": _PASSWORD},
            )
        finally:
            reset_email_provider()

        assert r.status_code == 200, r.text
        body = r.json()
        assert "pending_auth_ref" in body
        assert "access_token" not in body
        assert "refresh_token" not in body


# ---------------------------------------------------------------------------
# /me shape for organization-only users
# ---------------------------------------------------------------------------
class TestOrganizationOnlyMe:
    def test_me_returns_empty_roles_and_owner_organization(
        self, client, org_only_user,
    ):
        r = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {org_only_user['access_token']}"},
        )
        assert r.status_code == 200, r.text
        body = r.json()

        assert body["email"] == org_only_user["email"]
        assert body["roles"] == []
        assert len(body["organizations"]) == 1
        org_entry = body["organizations"][0]
        assert org_entry["name"] == org_only_user["org_name"]
        assert org_entry["role"] == "owner"
        assert isinstance(org_entry["id"], str) and org_entry["id"]


# ---------------------------------------------------------------------------
# Permission denials for organization-only users
# ---------------------------------------------------------------------------
class TestOrganizationOnlyPermissionDenials:
    def test_get_projects_returns_403(self, client, org_only_user):
        r = client.get(
            "/api/projects",
            headers={"Authorization": f"Bearer {org_only_user['access_token']}"},
        )
        assert r.status_code == 403, r.text
        body = r.json()
        assert body["error"]["code"] == 403

    def test_post_chat_returns_403(self, client, org_only_user):
        r = client.post(
            "/api/chat",
            json={"message": "hello"},
            headers={"Authorization": f"Bearer {org_only_user['access_token']}"},
        )
        assert r.status_code == 403, r.text
        body = r.json()
        assert body["error"]["code"] == 403

    def test_post_projects_start_returns_403(self, client, org_only_user):
        r = client.post(
            "/api/projects/start",
            json={"project_name": "Will Not Create", "module": "FI"},
            headers={"Authorization": f"Bearer {org_only_user['access_token']}"},
        )
        assert r.status_code == 403, r.text
        body = r.json()
        assert body["error"]["code"] == 403