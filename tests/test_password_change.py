"""
Tests for POST /api/auth/password.

Endpoint contract (verified against the current source):

  * Authenticated via `Depends(get_current_user)`. Not
    permission-guarded. `PROFILE_EDIT` is defined and granted to every
    application role, but is not enforced on this route — the endpoint
    behaves identically for individual and organization-only users.
  * On success returns 200 with body {"success": true}.
  * On wrong current password returns 400 with the application error
    envelope: {"error": {"code": 400, "message": "Current password is
    incorrect", "request_id": "..."}}.
  * On invalid payload (short/blocklisted/identical password, empty
    current, oversized fields) returns 422 with FastAPI's default
    validation response — not the application error envelope.
  * Does NOT invalidate access tokens issued before the change; the
    `change_password` docstring states this explicitly.

Request schema (`PasswordChangeRequest`):
  * current_password: 1..128 characters.
  * new_password: must satisfy `_validate_password_common_rules`
    (>=12, <=128, not whitespace-only, not on the common-password
    blocklist) and must differ from current_password.

Coverage:
  A. Successful change.
  B. Post-change authentication (new password works, old password
     does not, pre-change token still valid).
  C. Wrong current password.
  D. Unauthenticated request.
  E. Schema validation of the new password.
  F. Invalid current/new combinations.
  G. Unrelated user state preserved across a password change.
  H. Organization-only user follows the same flow.

Out of scope:
  * Signup password-validation tests — covered by
    tests/test_orchestrator_api.py.
  * Profile/picture behaviors — covered by
    tests/test_account_profile.py.
  * Token revocation semantics — the current implementation does not
    revoke tokens on password change; the docstring documents this as
    a known limitation. Not tested as a contract here.

No production code, migration, existing test, fixture, or
configuration is modified by this file.
"""
from __future__ import annotations

import uuid
from contextlib import contextmanager
from typing import Iterator, List

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.db.base import SessionLocal
from src.db.models import Organization, SessionRecord, User
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


def _unique_email(prefix: str = "pw") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}@example.com"


def _signup(
    client: TestClient,
    email: str,
    account_type: str = "functional_consultant",
    organization_name: str | None = None,
) -> str:
    """Sign up with an explicit account type and return the access
    token. `organization_name` is required only for the organization
    account type and is passed through when provided."""
    payload = {
        "email": email,
        "password": "testpassword123",
        "account_type": account_type,
    }
    if organization_name is not None:
        payload["organization_name"] = organization_name
    r = client.post("/api/auth/signup", json=payload)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _user_id_for_email(email: str) -> str:
    with _db_session() as db:
        uid = db.query(User.id).filter(User.email == email.lower()).scalar()
    assert uid is not None, f"no user row for {email!r}"
    return uid


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# Fixed passwords used by this file. Chosen to satisfy the schema:
# >= 12 chars, not on the blocklist, and not containing any email local
# part produced by `_unique_email` (which uses a hex token).
_CURRENT_PW = "testpassword123"
_NEW_PW = "newpassword4567"
_BLOCKLISTED_PW = "password1234"     # present in _COMMON_PASSWORDS
_SHORT_PW = "shortpw"                # 7 chars, < 12


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def client():
    """TestClient entered as a context manager so the lifespan runs."""
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


class _Registry:
    def __init__(self):
        self.emails: List[str] = []


@pytest.fixture
def created_users():
    """Track emails created during a test and delete their rows on
    teardown. Mirrors the cleanup in tests/test_account_profile.py."""
    r = _Registry()
    yield r
    if not r.emails:
        return
    lowered = [e.lower() for e in r.emails]
    with _db_session() as db:
        users = db.query(User).filter(User.email.in_(lowered)).all()
        if not users:
            return
        user_ids = [u.id for u in users]
        db.query(SessionRecord).filter(
            SessionRecord.user_id.in_(user_ids)
        ).delete(synchronize_session=False)
        db.query(Organization).filter(
            Organization.created_by.in_(user_ids)
        ).delete(synchronize_session=False)
        db.query(User).filter(
            User.id.in_(user_ids)
        ).delete(synchronize_session=False)
        db.commit()


# ===========================================================================
# A. Successful password change
# ===========================================================================
class TestSuccessfulChange:
    def test_changes_password_and_returns_success(
        self, client, created_users,
    ):
        """A signed-in user can change their password. The endpoint
        returns 200 with body {"success": true}; the response is not
        wrapped in the application error envelope."""
        email = _unique_email()
        created_users.emails.append(email)
        token = _signup(client, email)

        r = client.post(
            "/api/auth/password",
            json={
                "current_password": _CURRENT_PW,
                "new_password": _NEW_PW,
            },
            headers=_headers(token),
        )
        assert r.status_code == 200, r.text
        assert r.json() == {"success": True}


# ===========================================================================
# B. Post-change authentication
# ===========================================================================
class TestPostChangeAuthentication:
    def test_new_password_works_for_login(self, client, created_users):
        email = _unique_email()
        created_users.emails.append(email)
        token = _signup(client, email)

        r = client.post(
            "/api/auth/password",
            json={
                "current_password": _CURRENT_PW,
                "new_password": _NEW_PW,
            },
            headers=_headers(token),
        )
        assert r.status_code == 200, r.text

        r = client.post(
            "/api/auth/login",
            json={"email": email, "password": _NEW_PW},
        )
        assert r.status_code == 200, r.text
        assert "access_token" in r.json()

    def test_old_password_no_longer_works_for_login(self, client, created_users):
        email = _unique_email()
        created_users.emails.append(email)
        token = _signup(client, email)

        client.post(
            "/api/auth/password",
            json={
                "current_password": _CURRENT_PW,
                "new_password": _NEW_PW,
            },
            headers=_headers(token),
        )

        r = client.post(
            "/api/auth/login",
            json={"email": email, "password": _CURRENT_PW},
        )
        assert r.status_code == 401, r.text

    def test_pre_change_token_remains_valid(self, client, created_users):
        """The current `change_password` implementation does not
        invalidate tokens issued before the change. This test locks in
        that behavior so a future change that adds revocation surfaces
        as a focused failure rather than silently breaking any
        application that relied on the old behavior. The behavior is
        documented in the `change_password` docstring."""
        email = _unique_email()
        created_users.emails.append(email)
        token = _signup(client, email)

        r = client.post(
            "/api/auth/password",
            json={
                "current_password": _CURRENT_PW,
                "new_password": _NEW_PW,
            },
            headers=_headers(token),
        )
        assert r.status_code == 200, r.text

        # The same token issued before the change still authenticates.
        r = client.get("/api/auth/me", headers=_headers(token))
        assert r.status_code == 200, r.text
        assert r.json()["email"] == email


# ===========================================================================
# C. Wrong current password
# ===========================================================================
class TestWrongCurrentPassword:
    def test_returns_400_with_exact_error_envelope(
        self, client, created_users,
    ):
        """Wrong current password returns 400. The message is the exact
        string the route produces ("Current password is incorrect"),
        wrapped by the application's HTTPException handler in the
        standard error envelope."""
        email = _unique_email()
        created_users.emails.append(email)
        token = _signup(client, email)

        r = client.post(
            "/api/auth/password",
            json={
                "current_password": "notthecurrentpassword",
                "new_password": _NEW_PW,
            },
            headers=_headers(token),
        )
        assert r.status_code == 400, r.text
        body = r.json()
        assert "error" in body
        assert body["error"]["code"] == 400
        assert body["error"]["message"] == "Current password is incorrect"
        assert "request_id" in body["error"]

    def test_password_unchanged_after_rejection(self, client, created_users):
        """A rejected change leaves the stored hash intact: the original
        password still logs in, and the attempted new password does
        not."""
        email = _unique_email()
        created_users.emails.append(email)
        token = _signup(client, email)

        r = client.post(
            "/api/auth/password",
            json={
                "current_password": "notthecurrentpassword",
                "new_password": _NEW_PW,
            },
            headers=_headers(token),
        )
        assert r.status_code == 400

        # Original password still works.
        r = client.post(
            "/api/auth/login",
            json={"email": email, "password": _CURRENT_PW},
        )
        assert r.status_code == 200, r.text

        # Attempted new password does not work.
        r = client.post(
            "/api/auth/login",
            json={"email": email, "password": _NEW_PW},
        )
        assert r.status_code == 401, r.text


# ===========================================================================
# D. Unauthenticated request
# ===========================================================================
class TestUnauthenticated:
    def test_returns_401(self, client):
        r = client.post(
            "/api/auth/password",
            json={
                "current_password": _CURRENT_PW,
                "new_password": _NEW_PW,
            },
        )
        assert r.status_code == 401

    def test_invalid_token_returns_401(self, client):
        r = client.post(
            "/api/auth/password",
            json={
                "current_password": _CURRENT_PW,
                "new_password": _NEW_PW,
            },
            headers=_headers("not-a-real-token"),
        )
        assert r.status_code == 401


# ===========================================================================
# E. Schema validation of the new password
# ===========================================================================
class TestNewPasswordValidation:
    def test_short_new_password_rejected(self, client, created_users):
        email = _unique_email()
        created_users.emails.append(email)
        token = _signup(client, email)

        r = client.post(
            "/api/auth/password",
            json={
                "current_password": _CURRENT_PW,
                "new_password": _SHORT_PW,
            },
            headers=_headers(token),
        )
        assert r.status_code == 422, r.text

    def test_blocklisted_new_password_rejected(self, client, created_users):
        email = _unique_email()
        created_users.emails.append(email)
        token = _signup(client, email)

        r = client.post(
            "/api/auth/password",
            json={
                "current_password": _CURRENT_PW,
                "new_password": _BLOCKLISTED_PW,
            },
            headers=_headers(token),
        )
        assert r.status_code == 422, r.text

    def test_new_password_equal_to_current_rejected(self, client, created_users):
        """The schema's `_new_password_differs` validator rejects a
        change where the new password is identical to the current one,
        before the request reaches the route body. 422 with FastAPI's
        default validation shape."""
        email = _unique_email()
        created_users.emails.append(email)
        token = _signup(client, email)

        r = client.post(
            "/api/auth/password",
            json={
                "current_password": _CURRENT_PW,
                "new_password": _CURRENT_PW,
            },
            headers=_headers(token),
        )
        assert r.status_code == 422, r.text

    def test_whitespace_only_new_password_rejected(self, client, created_users):
        email = _unique_email()
        created_users.emails.append(email)
        token = _signup(client, email)

        r = client.post(
            "/api/auth/password",
            json={
                "current_password": _CURRENT_PW,
                "new_password": "                ",  # 16 spaces
            },
            headers=_headers(token),
        )
        assert r.status_code == 422, r.text


# ===========================================================================
# F. Invalid current/new combinations
# ===========================================================================
class TestInvalidCombinations:
    def test_empty_current_password_rejected(self, client, created_users):
        """`current_password` has `min_length=1`; an empty string fails
        at the schema layer with 422 before the route body runs."""
        email = _unique_email()
        created_users.emails.append(email)
        token = _signup(client, email)

        r = client.post(
            "/api/auth/password",
            json={
                "current_password": "",
                "new_password": _NEW_PW,
            },
            headers=_headers(token),
        )
        assert r.status_code == 422, r.text

    def test_overlong_new_password_rejected(self, client, created_users):
        """`new_password` max length is 128; 129 characters fails at
        the schema layer."""
        email = _unique_email()
        created_users.emails.append(email)
        token = _signup(client, email)

        r = client.post(
            "/api/auth/password",
            json={
                "current_password": _CURRENT_PW,
                "new_password": "x" * 129,
            },
            headers=_headers(token),
        )
        assert r.status_code == 422, r.text

    def test_missing_fields_rejected(self, client, created_users):
        email = _unique_email()
        created_users.emails.append(email)
        token = _signup(client, email)

        r = client.post(
            "/api/auth/password",
            json={"current_password": _CURRENT_PW},
            headers=_headers(token),
        )
        assert r.status_code == 422, r.text


# ===========================================================================
# G. Unrelated user state preserved
# ===========================================================================
class TestUnrelatedStatePreserved:
    def test_roles_and_organizations_unchanged_after_password_change(
        self, client, created_users,
    ):
        """A password change does not touch the user's application
        roles or organization memberships. This is the tenant/user
        state boundary: password mutation is confined to the
        `hashed_password` column."""
        email = _unique_email()
        created_users.emails.append(email)
        token = _signup(client, email)  # functional_consultant

        r = client.post(
            "/api/auth/password",
            json={
                "current_password": _CURRENT_PW,
                "new_password": _NEW_PW,
            },
            headers=_headers(token),
        )
        assert r.status_code == 200, r.text

        r = client.get("/api/auth/me", headers=_headers(token))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["roles"] == ["functional_consultant"]
        assert body["organizations"] == []

    def test_name_and_profile_picture_url_preserved(
        self, client, created_users,
    ):
        """A password change does not clear `name` or
        `profile_picture_url`."""
        email = _unique_email()
        created_users.emails.append(email)
        token = _signup(client, email)

        # Set a name first.
        client.patch(
            "/api/auth/settings",
            json={"name": "Preserved Name"},
            headers=_headers(token),
        )

        r = client.post(
            "/api/auth/password",
            json={
                "current_password": _CURRENT_PW,
                "new_password": _NEW_PW,
            },
            headers=_headers(token),
        )
        assert r.status_code == 200, r.text

        r = client.get("/api/auth/me", headers=_headers(token))
        body = r.json()
        assert body["name"] == "Preserved Name"
        # No profile picture was set, so the field is None — the
        # important contract is that the field is not silently changed
        # by the password change.
        assert body["profile_picture_url"] is None


# ===========================================================================
# H. Organization-only users
# ===========================================================================
class TestOrganizationOnlyUser:
    def test_can_change_password_without_application_role(
        self, client, created_users,
    ):
        """An organization-only user holds zero application roles and
        therefore zero permissions. If the route were guarded by
        `require_permission(PROFILE_EDIT)`, this user would receive
        403. The endpoint is on `get_current_user` only, so the change
        succeeds with 200 — the same confirmation as the profile
        settings endpoint."""
        email = _unique_email("orgonly-pw")
        created_users.emails.append(email)
        token = _signup(
            client,
            email,
            account_type="organization",
            organization_name="Password Test Org",
        )

        r = client.post(
            "/api/auth/password",
            json={
                "current_password": _CURRENT_PW,
                "new_password": _NEW_PW,
            },
            headers=_headers(token),
        )
        assert r.status_code == 200, r.text
        assert r.json() == {"success": True}

    def test_new_password_works_and_roles_remain_empty(
        self, client, created_users,
    ):
        """The organization-only user can log in with the new password,
        and still has roles == [] with the owner organization present
        on /me. The two axes remain independent of password state."""
        email = _unique_email("orgonly-pw2")
        created_users.emails.append(email)
        token = _signup(
            client,
            email,
            account_type="organization",
            organization_name="Password Test Org 2",
        )

        r = client.post(
            "/api/auth/password",
            json={
                "current_password": _CURRENT_PW,
                "new_password": _NEW_PW,
            },
            headers=_headers(token),
        )
        assert r.status_code == 200, r.text

        # New password works for login.
        r = client.post(
            "/api/auth/login",
            json={"email": email, "password": _NEW_PW},
        )
        assert r.status_code == 200, r.text
        new_token = r.json()["access_token"]

        # Roles still empty; organization membership still present.
        r = client.get("/api/auth/me", headers=_headers(new_token))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["roles"] == []
        assert len(body["organizations"]) == 1
        assert body["organizations"][0]["role"] == "owner"