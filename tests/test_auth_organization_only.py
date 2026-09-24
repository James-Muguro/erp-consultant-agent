"""
Integration tests for the organization-only user experience.

A user who signed up with account_type='organization' has:
  * exactly one Organization (created at signup),
  * exactly one OrganizationMembership with role='owner' for that
    organization,
  * zero UserRoleRecord rows.

Consequences exercised by this file:

  * The user can log in (authentication is independent of the
    application-role grants).
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

  * The 403 assertions deliberately choose routes whose permission
    guard runs on the dependency layer, before the route body. That
    means the response is produced by require_permission, not by
    _get_owned_session or by any body logic — the test is asserting
    the permission gate itself, not a downstream failure.

  * The user's organization and membership are not cleaned up
    explicitly by this file. The created_users fixture deletes
    organizations created_by the tracked users first (memberships
    cascade via organization_memberships.organization_id ON DELETE
    CASCADE), then deletes the users (any remaining rows cascade via
    their user_id FKs). This mirrors the cleanup pattern in
    tests/test_signup.py and tests/test_auth_me.py.

  * No production code, existing test file, fixture, migration, or
    product capability is modified by this file.
"""
from __future__ import annotations

import uuid
from contextlib import contextmanager
from typing import Iterator, List

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.db.base import SessionLocal
from src.db.models import Organization, User
from src.orchestrator_api import app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
@contextmanager
def _db_session() -> Iterator[Session]:
    """Local session lifecycle helper, matching the pattern used in
    tests/test_consistency_check_api.py."""
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


def _signup_organization(
    client: TestClient,
    email: str,
    org_name: str,
) -> str:
    """Sign up an organization account and return the access token."""
    r = client.post(
        "/api/auth/signup",
        json={
            "email": email,
            "password": "testpassword123",
            "account_type": "organization",
            "organization_name": org_name,
        },
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def client():
    """TestClient entered as a context manager so the lifespan runs."""
    with TestClient(app) as c:
        yield c


@pytest.fixture
def created_users():
    """Track emails created during a test and clean up their rows on
    teardown.

    Deletion order:
      1. Organizations created by these users (their memberships
         cascade via organization_memberships.organization_id ON
         DELETE CASCADE).
      2. The users themselves (any remaining rows cascade via their
         user_id FKs).

    A no-op when the test created no users.
    """
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
    """Sign up an organization-only user and return the signup
    credentials and access token.

    Returns a dict with:
      email           the unique email used
      password        the password used
      org_name        the organization name supplied at signup
      signup_token    the access token returned by signup
    """
    email = _unique_email()
    created_users.append(email)
    org_name = f"Org Only Test {uuid.uuid4().hex[:6]}"
    token = _signup_organization(client, email, org_name)
    return {
        "email": email,
        "password": "testpassword123",
        "org_name": org_name,
        "signup_token": token,
    }


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------
class TestOrganizationOnlyLogin:
    def test_can_log_in_after_signup(self, client, org_only_user):
        """Authentication resolves the user via the users table and a
        JWT subject. It does not consult application roles. An
        organization-only user therefore logs in successfully."""
        r = client.post(
            "/api/auth/login",
            json={
                "email": org_only_user["email"],
                "password": org_only_user["password"],
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert "access_token" in body
        assert body.get("token_type") == "bearer"

    def test_login_token_is_accepted_by_me(self, client, org_only_user):
        """The token from /login works on /me — proving the login token
        is a valid bearer credential for an org-only user."""
        r = client.post(
            "/api/auth/login",
            json={
                "email": org_only_user["email"],
                "password": org_only_user["password"],
            },
        )
        assert r.status_code == 200, r.text
        login_token = r.json()["access_token"]

        r = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {login_token}"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["email"] == org_only_user["email"]


# ---------------------------------------------------------------------------
# /me shape for organization-only users
# ---------------------------------------------------------------------------
class TestOrganizationOnlyMe:
    def test_me_returns_empty_roles_and_owner_organization(
        self, client, org_only_user,
    ):
        """Organization-only user's /me: roles is empty, organizations
        contains exactly one entry with role='owner' for the
        organization created at signup. The two axes are independent
        and neither is derived from the other."""
        r = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {org_only_user['signup_token']}"},
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
        """GET /api/projects is guarded by require_permission(
        PROJECT_READ). An organization-only user holds no application
        role and therefore no permissions; the guard rejects with 403
        before the route body runs."""
        r = client.get(
            "/api/projects",
            headers={"Authorization": f"Bearer {org_only_user['signup_token']}"},
        )
        assert r.status_code == 403, r.text
        body = r.json()
        assert body["error"]["code"] == 403

    def test_post_chat_returns_403(self, client, org_only_user):
        """POST /api/chat is guarded by require_permission(CHAT_SUBMIT).
        The permission check runs before any body-level session
        handling, so the org-only user is rejected at the guard."""
        r = client.post(
            "/api/chat",
            json={"message": "hello"},
            headers={"Authorization": f"Bearer {org_only_user['signup_token']}"},
        )
        assert r.status_code == 403, r.text
        body = r.json()
        assert body["error"]["code"] == 403

    def test_post_projects_start_returns_403(self, client, org_only_user):
        """POST /api/projects/start is guarded by require_permission(
        PROJECT_CREATE). Organization-only users hold no application
        role, so they cannot create projects in any context — not even
        in their own organization, because no organization-scoped
        project-creation endpoint exists yet and the current endpoint
        is not tenant-aware beyond the optional organization_id field.
        This is the documented gap; the test locks in the current
        behavior without implying the capability is unimplemented in
        the sense of "forgotten"."""
        r = client.post(
            "/api/projects/start",
            json={"project_name": "Will Not Create", "module": "FI"},
            headers={"Authorization": f"Bearer {org_only_user['signup_token']}"},
        )
        assert r.status_code == 403, r.text
        body = r.json()
        assert body["error"]["code"] == 403