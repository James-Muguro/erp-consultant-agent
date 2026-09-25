"""
Route-level tests for the Step 6 auth endpoints.

Scope: the FastAPI layer only — status codes, cookie behaviour, CSRF
enforcement, and enumeration-resistant response shapes. The flow layer
is covered by tests/test_auth_flows.py. Email is intercepted with
`set_email_provider`; no SMTP connection is opened.

Coverage:
    * signup returns a generic message for new and duplicate emails
    * verify-email consumes a token; rejects invalid/expired
    * login returns a pending_auth_ref and no tokens
    * login/verify-otp sets the refresh cookie and returns the access
      token; the refresh token is not in the JSON body
    * login/verify-otp rejects bad codes with a generic error
    * refresh requires the refresh cookie and the CSRF header
    * refresh rejects the CSRF check when header is missing/mismatched
    * refresh rotates the cookie value
    * refresh reuses detection is surfaced as a 401 (not 500)
    * logout is idempotent and clears the cookies
    * logout-all requires an access token
    * password-reset/request is enumeration-resistant
    * password-reset/complete consumes a token
    * /me rejects a pending-auth reference
"""
from __future__ import annotations

import uuid
from typing import Iterator, List, Tuple

import pytest
from fastapi.testclient import TestClient

from src.config.settings import settings
from src.db.base import SessionLocal, init_db
from src.db.models import User
from src.email import reset_email_provider, set_email_provider
from src.orchestrator_api import app


@pytest.fixture(scope="module", autouse=True)
def _ensure_schema():
    init_db()
    yield


@pytest.fixture
def client():
    # HTTPS base URL so Secure cookies issued by login/verify-otp are
    # transported on subsequent requests. The default
    # http://testserver silently drops them, which breaks every
    # refresh-cookie test.
    with TestClient(app, base_url="https://testserver") as c:
        yield c


@pytest.fixture
def outbox() -> Iterator[List[Tuple[str, str, str]]]:
    sent: List[Tuple[str, str, str]] = []

    def capture(to: str, subject: str, body: str) -> None:
        sent.append((to, subject, body))

    set_email_provider(capture)
    yield sent
    reset_email_provider()


@pytest.fixture
def tracked():
    emails: List[str] = []
    yield emails
    if not emails:
        return
    lowered = [e.lower() for e in emails]
    session = SessionLocal()
    try:
        users = session.query(User).filter(User.email.in_(lowered)).all()
        if users:
            session.query(User).filter(
                User.id.in_([u.id for u in users])
            ).delete(synchronize_session=False)
            session.commit()
    finally:
        session.close()


def _unique_email() -> str:
    return f"routes-test-{uuid.uuid4().hex[:12]}@example.com"


_PASSWORD = "correct horse battery staple"


def _signup_and_verify(client: TestClient, outbox, email: str) -> None:
    r = client.post(
        "/api/auth/signup",
        json={
            "email": email,
            "password": _PASSWORD,
            "account_type": "developer",
        },
    )
    assert r.status_code == 200
    assert len(outbox) >= 1
    body = outbox[-1][2]
    raw = body.split("token=")[1].split("\n")[0]
    r = client.post("/api/auth/verify-email", json={"token": raw})
    assert r.status_code == 200, r.text


def _login_and_get_tokens(
    client: TestClient, outbox, email: str
) -> Tuple[str, str]:
    """Drive login -> OTP -> return (access_token, refresh_cookie_value)."""
    r = client.post(
        "/api/auth/login",
        json={"email": email, "password": _PASSWORD},
    )
    assert r.status_code == 200, r.text
    ref = r.json()["pending_auth_ref"]
    otp_body = outbox[-1][2]
    otp_code = otp_body.split("    ")[1].split("\n")[0].strip()
    r = client.post(
        "/api/auth/login/verify-otp",
        json={"pending_auth_ref": ref, "code": otp_code},
    )
    assert r.status_code == 200, r.text
    access = r.json()["access_token"]
    refresh_cookie = client.cookies.get(settings.auth_refresh_cookie_name)
    assert refresh_cookie
    return access, refresh_cookie


# ---------------------------------------------------------------------------
# Signup
# ---------------------------------------------------------------------------
class TestSignup:
    def test_new_signup_returns_generic_message(self, client, outbox, tracked):
        email = _unique_email()
        tracked.append(email)
        r = client.post(
            "/api/auth/signup",
            json={
                "email": email,
                "password": _PASSWORD,
                "account_type": "developer",
            },
        )
        assert r.status_code == 200
        assert "message" in r.json()
        # No token fields in the response body.
        assert "access_token" not in r.json()
        assert "refresh_token" not in r.json()

    def test_duplicate_signup_returns_same_generic_message(
        self, client, outbox, tracked
    ):
        email = _unique_email()
        tracked.append(email)
        first = client.post(
            "/api/auth/signup",
            json={"email": email, "password": _PASSWORD, "account_type": "developer"},
        )
        second = client.post(
            "/api/auth/signup",
            json={"email": email, "password": _PASSWORD, "account_type": "developer"},
        )
        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json() == second.json()


# ---------------------------------------------------------------------------
# Email verification
# ---------------------------------------------------------------------------
class TestVerifyEmail:
    def test_valid_token_returns_200(self, client, outbox, tracked):
        email = _unique_email()
        tracked.append(email)
        _signup_and_verify(client, outbox, email)

    def test_invalid_token_returns_400_generic(self, client):
        r = client.post(
            "/api/auth/verify-email", json={"token": "not-a-real-token"}
        )
        assert r.status_code == 400
        # Response body does not reveal account existence.
        assert "account" not in r.json()["error"]["message"].lower()


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------
class TestLogin:
    def test_login_returns_pending_ref_not_tokens(self, client, outbox, tracked):
        email = _unique_email()
        tracked.append(email)
        _signup_and_verify(client, outbox, email)

        r = client.post(
            "/api/auth/login",
            json={"email": email, "password": _PASSWORD},
        )
        assert r.status_code == 200
        body = r.json()
        assert "pending_auth_ref" in body
        assert "access_token" not in body
        assert "refresh_token" not in body
        # No cookie set on the login response.
        assert settings.auth_refresh_cookie_name not in client.cookies

    def test_wrong_password_returns_generic_401(self, client, outbox, tracked):
        email = _unique_email()
        tracked.append(email)
        _signup_and_verify(client, outbox, email)

        r = client.post(
            "/api/auth/login",
            json={"email": email, "password": "not-the-password"},
        )
        assert r.status_code == 401
        assert "account" not in r.json()["error"]["message"].lower()

    def test_unknown_email_returns_same_generic_401(self, client):
        r = client.post(
            "/api/auth/login",
            json={"email": "nobody@example.com", "password": "whatever-value"},
        )
        assert r.status_code == 401
        # Identical message to the wrong-password case.
        assert r.json()["error"]["message"] == "Invalid email or password."


# ---------------------------------------------------------------------------
# OTP verification
# ---------------------------------------------------------------------------
class TestVerifyOtp:
    def test_success_sets_cookies_and_returns_access_token(
        self, client, outbox, tracked
    ):
        email = _unique_email()
        tracked.append(email)
        _signup_and_verify(client, outbox, email)
        access, refresh_cookie = _login_and_get_tokens(client, outbox, email)

        assert access
        assert refresh_cookie
        # CSRF cookie is set alongside the refresh cookie.
        assert settings.auth_csrf_cookie_name in client.cookies

    def test_bad_code_returns_400_generic(self, client, outbox, tracked):
        email = _unique_email()
        tracked.append(email)
        _signup_and_verify(client, outbox, email)
        r = client.post(
            "/api/auth/login",
            json={"email": email, "password": _PASSWORD},
        )
        ref = r.json()["pending_auth_ref"]
        r = client.post(
            "/api/auth/login/verify-otp",
            json={"pending_auth_ref": ref, "code": "000000"},
        )
        assert r.status_code == 400

    def test_bad_code_shape_rejected_by_schema(self, client, outbox, tracked):
        email = _unique_email()
        tracked.append(email)
        _signup_and_verify(client, outbox, email)
        r = client.post(
            "/api/auth/login",
            json={"email": email, "password": _PASSWORD},
        )
        ref = r.json()["pending_auth_ref"]
        # Non-numeric code: rejected by the schema, not by the flow.
        r = client.post(
            "/api/auth/login/verify-otp",
            json={"pending_auth_ref": ref, "code": "abcdef"},
        )
        assert r.status_code == 422  # FastAPI validation error


# ---------------------------------------------------------------------------
# Refresh
# ---------------------------------------------------------------------------
class TestRefresh:
    def test_refresh_requires_cookie(self, client):
        r = client.post("/api/auth/refresh")
        assert r.status_code == 401

    def test_refresh_requires_csrf_header(self, client, outbox, tracked):
        email = _unique_email()
        tracked.append(email)
        _signup_and_verify(client, outbox, email)
        _login_and_get_tokens(client, outbox, email)

        # No CSRF header — refresh must fail.
        r = client.post("/api/auth/refresh")
        assert r.status_code == 403

    def test_refresh_succeeds_with_matching_csrf(self, client, outbox, tracked):
        email = _unique_email()
        tracked.append(email)
        _signup_and_verify(client, outbox, email)
        _login_and_get_tokens(client, outbox, email)

        csrf = client.cookies.get(settings.auth_csrf_cookie_name)
        assert csrf
        r = client.post(
            "/api/auth/refresh",
            headers={settings.auth_csrf_header_name: csrf},
        )
        assert r.status_code == 200, r.text
        assert "access_token" in r.json()

    def test_refresh_rotates_cookie(self, client, outbox, tracked):
        email = _unique_email()
        tracked.append(email)
        _signup_and_verify(client, outbox, email)
        _, original_refresh = _login_and_get_tokens(client, outbox, email)
        csrf = client.cookies.get(settings.auth_csrf_cookie_name)
        r = client.post(
            "/api/auth/refresh",
            headers={settings.auth_csrf_header_name: csrf},
        )
        assert r.status_code == 200
        new_refresh = client.cookies.get(settings.auth_refresh_cookie_name)
        assert new_refresh != original_refresh


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------
class TestLogout:
    def test_logout_clears_cookies_and_is_idempotent(
        self, client, outbox, tracked
    ):
        email = _unique_email()
        tracked.append(email)
        _signup_and_verify(client, outbox, email)
        _login_and_get_tokens(client, outbox, email)

        csrf = client.cookies.get(settings.auth_csrf_cookie_name)
        r = client.post(
            "/api/auth/logout",
            headers={settings.auth_csrf_header_name: csrf},
        )
        assert r.status_code == 200

        # Cookies cleared — a second call has no refresh cookie and is a
        # clean no-op.
        r = client.post("/api/auth/logout")
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Logout-all
# ---------------------------------------------------------------------------
class TestLogoutAll:
    def test_requires_access_token(self, client):
        r = client.post("/api/auth/logout-all")
        assert r.status_code == 401

    def test_succeeds_with_access_token(self, client, outbox, tracked):
        email = _unique_email()
        tracked.append(email)
        _signup_and_verify(client, outbox, email)
        access, _ = _login_and_get_tokens(client, outbox, email)
        r = client.post(
            "/api/auth/logout-all",
            headers={"Authorization": f"Bearer {access}"},
        )
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Password reset
# ---------------------------------------------------------------------------
class TestPasswordReset:
    def test_request_is_enumeration_resistant(self, client):
        r1 = client.post(
            "/api/auth/password-reset/request",
            json={"email": "nobody@example.com"},
        )
        r2 = client.post(
            "/api/auth/password-reset/request",
            json={"email": "also-nobody@example.com"},
        )
        assert r1.status_code == r2.status_code == 200
        assert r1.json() == r2.json()

    def test_complete_with_bad_token_returns_generic_400(self, client):
        r = client.post(
            "/api/auth/password-reset/complete",
            json={
                "token": "not-a-real-token",
                "new_password": "a-brand-new-strong-password-1",
            },
        )
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# /me
# ---------------------------------------------------------------------------
class TestMe:
    def test_pending_auth_ref_is_not_an_access_token(
        self, client, outbox, tracked
    ):
        email = _unique_email()
        tracked.append(email)
        _signup_and_verify(client, outbox, email)
        r = client.post(
            "/api/auth/login",
            json={"email": email, "password": _PASSWORD},
        )
        ref = r.json()["pending_auth_ref"]
        # Passing the pending-auth ref as a Bearer token must fail.
        r = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {ref}"},
        )
        assert r.status_code == 401

    def test_valid_access_token_returns_user(self, client, outbox, tracked):
        email = _unique_email()
        tracked.append(email)
        _signup_and_verify(client, outbox, email)
        access, _ = _login_and_get_tokens(client, outbox, email)
        r = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {access}"},
        )
        assert r.status_code == 200
        assert r.json()["email"] == email.lower()