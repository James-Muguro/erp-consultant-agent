"""
Tests for POST /api/auth/password.

Endpoint contract (verified against the current source):

  * Authenticated via `Depends(get_current_user)`. Not
    permission-guarded. `PROFILE_EDIT` is defined and granted to every
    application role, but is not enforced on this route — the endpoint
    behaves identically for individual and organization-only users.
  * On success returns 200 with body {"success": true}.
  * On wrong current password returns 400 with the application error
    envelope.
  * On invalid payload (short/blocklisted/identical password, empty
    current, oversized fields) returns 422 with FastAPI's default
    validation response.
  * Does NOT invalidate access tokens issued before the change.

Authentication helper: `_signup_and_authenticate` completes the full
new flow (signup → verify-email → login → verify-otp) with the email
abstraction mocked, matching the pattern in
tests/test_auth_lifecycle.py.

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

No production code, migration, existing test, fixture, or
configuration is modified by this file.
"""
from __future__ import annotations

import uuid
from contextlib import contextmanager
from typing import Iterator, List, Tuple

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.db.base import SessionLocal
from src.db.models import Organization, SessionRecord, User
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


def _unique_email(prefix: str = "pw") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}@example.com"


_CURRENT_PW = "testpassword123"
_NEW_PW = "newpassword4567"
_BLOCKLISTED_PW = "password1234"
_SHORT_PW = "shortpw"


def _signup_and_authenticate(
    client: TestClient,
    email: str,
    account_type: str = "functional_consultant",
    organization_name: str | None = None,
) -> str:
    """Complete the full auth flow and return an access token. The
    email abstraction is mocked for the duration so no SMTP connection
    is attempted."""
    captured: List[Tuple[str, str, str]] = []

    def _capture(to: str, subject: str, body: str) -> None:
        captured.append((to, subject, body))

    set_email_provider(_capture)
    try:
        payload = {
            "email": email,
            "password": _CURRENT_PW,
            "account_type": account_type,
        }
        if organization_name is not None:
            payload["organization_name"] = organization_name

        r = client.post("/api/auth/signup", json=payload)
        assert r.status_code == 200, f"signup failed: {r.text}"

        verify_body = captured[-1][2]
        raw_verify = verify_body.split("token=")[1].split("\n")[0]
        r = client.post(
            "/api/auth/verify-email", json={"token": raw_verify}
        )
        assert r.status_code == 200, f"verify-email failed: {r.text}"

        r = client.post(
            "/api/auth/login",
            json={"email": email, "password": _CURRENT_PW},
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


def _user_id_for_email(email: str) -> str:
    with _db_session() as db:
        uid = db.query(User.id).filter(User.email == email.lower()).scalar()
    assert uid is not None, f"no user row for {email!r}"
    return uid


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _reset_email_provider_after_test():
    yield
    reset_email_provider()


@pytest.fixture
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


class _Registry:
    def __init__(self):
        self.emails: List[str] = []


@pytest.fixture
def created_users():
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
        email = _unique_email()
        created_users.emails.append(email)
        token = _signup_and_authenticate(client, email)

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
        token = _signup_and_authenticate(client, email)

        r = client.post(
            "/api/auth/password",
            json={
                "current_password": _CURRENT_PW,
                "new_password": _NEW_PW,
            },
            headers=_headers(token),
        )
        assert r.status_code == 200, r.text

        # Login now returns pending_auth_ref; a successful response
        # confirms the new password is accepted.
        r = client.post(
            "/api/auth/login",
            json={"email": email, "password": _NEW_PW},
        )
        assert r.status_code == 200, r.text
        assert "pending_auth_ref" in r.json()

    def test_old_password_no_longer_works_for_login(self, client, created_users):
        email = _unique_email()
        created_users.emails.append(email)
        token = _signup_and_authenticate(client, email)

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
        email = _unique_email()
        created_users.emails.append(email)
        token = _signup_and_authenticate(client, email)

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
        assert r.json()["email"] == email


# ===========================================================================
# C. Wrong current password
# ===========================================================================
class TestWrongCurrentPassword:
    def test_returns_400_with_exact_error_envelope(
        self, client, created_users,
    ):
        email = _unique_email()
        created_users.emails.append(email)
        token = _signup_and_authenticate(client, email)

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
        email = _unique_email()
        created_users.emails.append(email)
        token = _signup_and_authenticate(client, email)

        r = client.post(
            "/api/auth/password",
            json={
                "current_password": "notthecurrentpassword",
                "new_password": _NEW_PW,
            },
            headers=_headers(token),
        )
        assert r.status_code == 400

        r = client.post(
            "/api/auth/login",
            json={"email": email, "password": _CURRENT_PW},
        )
        assert r.status_code == 200, r.text

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
        token = _signup_and_authenticate(client, email)

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
        token = _signup_and_authenticate(client, email)

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
        email = _unique_email()
        created_users.emails.append(email)
        token = _signup_and_authenticate(client, email)

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
        token = _signup_and_authenticate(client, email)

        r = client.post(
            "/api/auth/password",
            json={
                "current_password": _CURRENT_PW,
                "new_password": "                ",
            },
            headers=_headers(token),
        )
        assert r.status_code == 422, r.text


# ===========================================================================
# F. Invalid current/new combinations
# ===========================================================================
class TestInvalidCombinations:
    def test_empty_current_password_rejected(self, client, created_users):
        email = _unique_email()
        created_users.emails.append(email)
        token = _signup_and_authenticate(client, email)

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
        email = _unique_email()
        created_users.emails.append(email)
        token = _signup_and_authenticate(client, email)

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
        token = _signup_and_authenticate(client, email)

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
        email = _unique_email()
        created_users.emails.append(email)
        token = _signup_and_authenticate(client, email)

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
        email = _unique_email()
        created_users.emails.append(email)
        token = _signup_and_authenticate(client, email)

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
        assert body["profile_picture_url"] is None


# ===========================================================================
# H. Organization-only users
# ===========================================================================
class TestOrganizationOnlyUser:
    def test_can_change_password_without_application_role(
        self, client, created_users,
    ):
        email = _unique_email("orgonly-pw")
        created_users.emails.append(email)
        token = _signup_and_authenticate(
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
        email = _unique_email("orgonly-pw2")
        created_users.emails.append(email)
        token = _signup_and_authenticate(
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

        # A successful login response now confirms only that the
        # password was accepted; token acquisition is a separate step.
        r = client.post(
            "/api/auth/login",
            json={"email": email, "password": _NEW_PW},
        )
        assert r.status_code == 200, r.text
        assert "pending_auth_ref" in r.json()

        # The pre-change token still authenticates /me, and the
        # response preserves the org-only shape.
        r = client.get("/api/auth/me", headers=_headers(token))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["roles"] == []
        assert len(body["organizations"]) == 1
        assert body["organizations"][0]["role"] == "owner"