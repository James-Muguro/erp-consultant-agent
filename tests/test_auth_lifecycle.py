"""
Step 9 integration tests: complete authentication lifecycle and
end-to-end failure modes through the HTTP layer.

Scope: FastAPI + flows + DB + cookies, exercised end-to-end. SMTP is
mocked via set_email_provider; no external network calls are made.

Uses TestClient with base_url="https://testserver". Cookies issued with
Secure=True (the Step 3 default) are only sent over HTTPS, so the
default http://testserver would silently drop them and every
state-changing test would fail. Using https://testserver matches the
production cookie policy.

Coverage:
    signup -> verify -> login -> OTP -> /me -> refresh -> logout
    logout-all-devices
    password reset end-to-end
    refresh rotation and reuse detection
    expired / used tokens
    progressive lockout
    OTP attempt exhaustion
    multiple sessions for the same user
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Iterator, List, Tuple

import pytest
from fastapi.testclient import TestClient

from src.config.settings import settings
from src.db.base import SessionLocal, init_db
from src.db.models import (
    AuthAuditEvent,
    AuthEmailVerificationToken,
    AuthOtpRecord,
    AuthPasswordResetToken,
    Organization,
    OrganizationMembership,
    User,
    UserRoleRecord,
)
from src.email import reset_email_provider, set_email_provider
from src.orchestrator_api import app


_PASSWORD = "correct horse battery staple"
_NEW_PASSWORD = "a-different-strong-password-7"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module", autouse=True)
def _ensure_schema():
    init_db()
    yield


@pytest.fixture
def client():
    """HTTPS TestClient so Secure cookies are echoed on subsequent
    requests, matching the production cookie policy."""
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
    """Track emails of users created during a test; clean up every
    derived row on teardown.

    Audit rows use ON DELETE SET NULL for user_id, so they are deleted
    explicitly. Organizations are deleted before users so the RESTRICT
    FK from sessions.organization_id is not exercised (tests do not
    create org-owned projects)."""
    emails: List[str] = []
    yield emails
    if not emails:
        return
    lowered = [e.lower() for e in emails]
    session = SessionLocal()
    try:
        users = session.query(User).filter(User.email.in_(lowered)).all()
        if not users:
            return
        user_ids = [u.id for u in users]
        session.query(AuthAuditEvent).filter(
            AuthAuditEvent.user_id.in_(user_ids)
        ).delete(synchronize_session=False)
        session.query(Organization).filter(
            Organization.created_by.in_(user_ids)
        ).delete(synchronize_session=False)
        session.query(User).filter(
            User.id.in_(user_ids)
        ).delete(synchronize_session=False)
        session.commit()
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _unique_email() -> str:
    return f"lifecycle-test-{uuid.uuid4().hex[:12]}@example.com"


def _extract_verification_token(outbox: List[Tuple[str, str, str]]) -> str:
    body = outbox[-1][2]
    return body.split("token=")[1].split("\n")[0]


def _extract_otp(outbox: List[Tuple[str, str, str]]) -> str:
    body = outbox[-1][2]
    return body.split("    ")[1].split("\n")[0].strip()


def _extract_reset_token(outbox: List[Tuple[str, str, str]]) -> str:
    body = outbox[-1][2]
    return body.split("token=")[1].split("\n")[0]


def _signup(client, outbox, tracked, email, account_type="developer", org_name=None):
    payload = {"email": email, "password": _PASSWORD, "account_type": account_type}
    if org_name is not None:
        payload["organization_name"] = org_name
    r = client.post("/api/auth/signup", json=payload)
    assert r.status_code == 200, r.text
    tracked.append(email)
    return r


def _verify_email(client, outbox) -> None:
    token = _extract_verification_token(outbox)
    r = client.post("/api/auth/verify-email", json={"token": token})
    assert r.status_code == 200, r.text


def _login_complete(client, outbox, email, password=_PASSWORD) -> dict:
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    ref = r.json()["pending_auth_ref"]
    code = _extract_otp(outbox)
    r = client.post(
        "/api/auth/login/verify-otp",
        json={"pending_auth_ref": ref, "code": code},
    )
    assert r.status_code == 200, r.text
    return r.json()


def _signup_verify_login(client, outbox, tracked, email):
    _signup(client, outbox, tracked, email)
    _verify_email(client, outbox)
    return _login_complete(client, outbox, email)


# ---------------------------------------------------------------------------
# Full lifecycle
# ---------------------------------------------------------------------------
class TestFullLifecycle:
    def test_signup_to_logout(self, client, outbox, tracked):
        email = _unique_email()
        tokens = _signup_verify_login(client, outbox, tracked, email)

        # Access token in body; refresh token never in body.
        assert tokens["access_token"]
        assert "refresh_token" not in tokens
        assert "token_type" in tokens
        assert "expires_in_minutes" in tokens

        # /me works.
        r = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["email"] == email.lower()
        assert body["roles"] == ["developer"]
        assert body["organizations"] == []

        # Refresh cookie and CSRF cookie present in the client jar.
        assert client.cookies.get(settings.auth_refresh_cookie_name)
        assert client.cookies.get(settings.auth_csrf_cookie_name)

        # Refresh rotates cookies.
        old_refresh = client.cookies.get(settings.auth_refresh_cookie_name)
        csrf = client.cookies.get(settings.auth_csrf_cookie_name)
        r = client.post(
            "/api/auth/refresh",
            headers={settings.auth_csrf_header_name: csrf},
        )
        assert r.status_code == 200, r.text
        new_refresh = client.cookies.get(settings.auth_refresh_cookie_name)
        assert new_refresh != old_refresh

        # Logout revokes the current refresh token and clears cookies.
        csrf = client.cookies.get(settings.auth_csrf_cookie_name)
        r = client.post(
            "/api/auth/logout",
            headers={settings.auth_csrf_header_name: csrf},
        )
        assert r.status_code == 200

    def test_logout_all_revokes_multiple_sessions(self, client, outbox, tracked):
        email = _unique_email()
        _signup(client, outbox, tracked, email)
        _verify_email(client, outbox)

        # First session.
        tokens1 = _login_complete(client, outbox, email)
        refresh1 = client.cookies.get(settings.auth_refresh_cookie_name)
        csrf1 = client.cookies.get(settings.auth_csrf_cookie_name)

        # Second session, using a fresh client so the first session's
        # cookies are preserved for verification afterward.
        second = TestClient(app, base_url="https://testserver")
        with second:
            r = second.post(
                "/api/auth/login",
                json={"email": email, "password": _PASSWORD},
            )
            ref2 = r.json()["pending_auth_ref"]
            code2 = _extract_otp(outbox)
            r = second.post(
                "/api/auth/login/verify-otp",
                json={"pending_auth_ref": ref2, "code": code2},
            )
            assert r.status_code == 200
            refresh2 = second.cookies.get(settings.auth_refresh_cookie_name)
            assert refresh2 != refresh1

            # Logout-all from session 2 using its own access token.
            access2 = r.json()["access_token"]
            r = second.post(
                "/api/auth/logout-all",
                headers={"Authorization": f"Bearer {access2}"},
            )
            assert r.status_code == 200

        # Session 1's refresh token is now revoked. Attempting to
        # refresh from the first client fails.
        r = client.post(
            "/api/auth/refresh",
            headers={settings.auth_csrf_header_name: csrf1},
        )
        assert r.status_code == 401

    def test_password_reset_replaces_password_and_revokes_sessions(
        self, client, outbox, tracked
    ):
        email = _unique_email()
        _signup_verify_login(client, outbox, tracked, email)
        csrf = client.cookies.get(settings.auth_csrf_cookie_name)

        # Request + complete password reset.
        r = client.post(
            "/api/auth/password-reset/request", json={"email": email}
        )
        assert r.status_code == 200
        reset_token = _extract_reset_token(outbox)
        r = client.post(
            "/api/auth/password-reset/complete",
            json={"token": reset_token, "new_password": _NEW_PASSWORD},
        )
        assert r.status_code == 200

        # Existing session is revoked: refresh fails.
        r = client.post(
            "/api/auth/refresh",
            headers={settings.auth_csrf_header_name: csrf},
        )
        assert r.status_code == 401

        # Old password no longer authenticates.
        r = client.post(
            "/api/auth/login", json={"email": email, "password": _PASSWORD}
        )
        assert r.status_code == 401

        # New password authenticates.
        r = client.post(
            "/api/auth/login",
            json={"email": email, "password": _NEW_PASSWORD},
        )
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Refresh rotation and reuse detection
# ---------------------------------------------------------------------------
class TestRefreshRotation:
    def test_reuse_of_rotated_token_revokes_family(
        self, client, outbox, tracked
    ):
        email = _unique_email()
        _signup_verify_login(client, outbox, tracked, email)
        original_refresh = client.cookies.get(settings.auth_refresh_cookie_name)
        csrf = client.cookies.get(settings.auth_csrf_cookie_name)

        # Rotate once: new refresh cookie.
        r = client.post(
            "/api/auth/refresh",
            headers={settings.auth_csrf_header_name: csrf},
        )
        assert r.status_code == 200
        rotated_refresh = client.cookies.get(settings.auth_refresh_cookie_name)
        assert rotated_refresh != original_refresh

        # Reuse the ORIGINAL (now revoked) refresh token from a fresh
        # client carrying only that cookie and the CSRF cookie.
        reused = TestClient(app, base_url="https://testserver")
        with reused:
            reused.cookies.set(settings.auth_refresh_cookie_name, original_refresh)
            reused.cookies.set(settings.auth_csrf_cookie_name, csrf)
            r = reused.post(
                "/api/auth/refresh",
                headers={settings.auth_csrf_header_name: csrf},
            )
            assert r.status_code == 401

        # The rotated token is now also invalid (family revoked).
        rotated_client = TestClient(app, base_url="https://testserver")
        with rotated_client:
            rotated_client.cookies.set(
                settings.auth_refresh_cookie_name, rotated_refresh
            )
            rotated_client.cookies.set(settings.auth_csrf_cookie_name, csrf)
            r = rotated_client.post(
                "/api/auth/refresh",
                headers={settings.auth_csrf_header_name: csrf},
            )
            assert r.status_code == 401


# ---------------------------------------------------------------------------
# Email verification boundaries
# ---------------------------------------------------------------------------
class TestEmailVerificationBoundaries:
    def test_used_verification_token_rejected(self, client, outbox, tracked):
        email = _unique_email()
        _signup(client, outbox, tracked, email)
        token = _extract_verification_token(outbox)

        r = client.post("/api/auth/verify-email", json={"token": token})
        assert r.status_code == 200
        r = client.post("/api/auth/verify-email", json={"token": token})
        assert r.status_code == 400

    def test_expired_verification_token_rejected(self, client, outbox, tracked):
        email = _unique_email()
        _signup(client, outbox, tracked, email)
        token = _extract_verification_token(outbox)

        # Backdate the verification token.
        session = SessionLocal()
        try:
            user = session.query(User).filter(
                User.email == email.lower()
            ).one()
            row = session.query(AuthEmailVerificationToken).filter(
                AuthEmailVerificationToken.user_id == user.id
            ).one()
            row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            session.commit()
        finally:
            session.close()

        r = client.post("/api/auth/verify-email", json={"token": token})
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# OTP boundaries
# ---------------------------------------------------------------------------
class TestOtpBoundaries:
    def test_wrong_otp_returns_generic_400(self, client, outbox, tracked):
        email = _unique_email()
        _signup(client, outbox, tracked, email)
        _verify_email(client, outbox)

        r = client.post(
            "/api/auth/login", json={"email": email, "password": _PASSWORD}
        )
        ref = r.json()["pending_auth_ref"]
        r = client.post(
            "/api/auth/login/verify-otp",
            json={"pending_auth_ref": ref, "code": "0" * settings.otp_length},
        )
        assert r.status_code == 400
        assert "error" in r.json()

    def test_attempt_limit_invalidates_even_correct_code(
        self, client, outbox, tracked
    ):
        email = _unique_email()
        _signup(client, outbox, tracked, email)
        _verify_email(client, outbox)

        r = client.post(
            "/api/auth/login", json={"email": email, "password": _PASSWORD}
        )
        ref = r.json()["pending_auth_ref"]
        correct = _extract_otp(outbox)

        # Burn attempts.
        for _ in range(settings.otp_max_attempts + 2):
            r = client.post(
                "/api/auth/login/verify-otp",
                json={"pending_auth_ref": ref, "code": "0" * settings.otp_length},
            )
            assert r.status_code == 400

        # Correct code now fails because the OTP is invalidated.
        r = client.post(
            "/api/auth/login/verify-otp",
            json={"pending_auth_ref": ref, "code": correct},
        )
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# Progressive login protection
# ---------------------------------------------------------------------------
class TestProgressiveLoginProtection:
    def test_lockout_after_threshold(self, client, outbox, tracked, monkeypatch):
        monkeypatch.setattr(settings, "login_max_failed_attempts", 3)
        email = _unique_email()
        _signup(client, outbox, tracked, email)
        _verify_email(client, outbox)

        for _ in range(3):
            r = client.post(
                "/api/auth/login",
                json={"email": email, "password": "wrong-password-value"},
            )
            assert r.status_code == 401

        # Even the correct password is now rejected with the same
        # generic message (no lockout disclosure).
        r = client.post(
            "/api/auth/login", json={"email": email, "password": _PASSWORD}
        )
        assert r.status_code == 401
        assert "locked" not in r.json()["error"]["message"].lower()
        assert "account" not in r.json()["error"]["message"].lower()

    def test_password_reset_clears_lockout(
        self, client, outbox, tracked, monkeypatch
    ):
        monkeypatch.setattr(settings, "login_max_failed_attempts", 3)
        email = _unique_email()
        _signup(client, outbox, tracked, email)
        _verify_email(client, outbox)

        for _ in range(3):
            client.post(
                "/api/auth/login",
                json={"email": email, "password": "wrong-password-value"},
            )

        # Reset the password; lockout must be cleared.
        r = client.post(
            "/api/auth/password-reset/request", json={"email": email}
        )
        assert r.status_code == 200
        reset_token = _extract_reset_token(outbox)
        r = client.post(
            "/api/auth/password-reset/complete",
            json={"token": reset_token, "new_password": _NEW_PASSWORD},
        )
        assert r.status_code == 200

        # New password authenticates; account is not locked.
        r = client.post(
            "/api/auth/login",
            json={"email": email, "password": _NEW_PASSWORD},
        )
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Organization signup
# ---------------------------------------------------------------------------
class TestOrganizationSignup:
    def test_org_signup_creates_owner_and_no_role(
        self, client, outbox, tracked
    ):
        email = _unique_email()
        org_name = f"Lifecycle Org {uuid.uuid4().hex[:6]}"
        _signup(
            client, outbox, tracked, email,
            account_type="organization", org_name=org_name,
        )
        _verify_email(client, outbox)
        tokens = _login_complete(client, outbox, email)

        r = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )
        assert r.status_code == 200
        body = r.json()
        # Application roles remain separate from organization membership.
        assert body["roles"] == []
        assert len(body["organizations"]) == 1
        assert body["organizations"][0]["name"] == org_name
        assert body["organizations"][0]["role"] == "owner"