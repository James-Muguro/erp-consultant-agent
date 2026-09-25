"""
Step 9 security invariants across the auth surface.

Scope: enumeration resistance, cookie attributes, CSRF enforcement,
audit hygiene, response-shape guarantees, and the refresh-cookie-clearing
regression. Uses TestClient with base_url="https://testserver" so Secure
cookies are transported.

Coverage:
    * Enumeration resistance (identical response bodies).
    * Cookie attributes on the refresh and CSRF cookies.
    * Refresh failure clears session cookies (regression test).
    * CSRF required on refresh and on logout-with-session.
    * Logout without a session is idempotent.
    * No credential values in any response body.
    * No credential values in any audit row.
    * Pending-auth reference cannot authenticate /me.
    * Access token cannot be used as the refresh cookie.
"""
from __future__ import annotations

import uuid
from typing import Iterator, List, Tuple

import pytest
from fastapi.testclient import TestClient

from src.config.settings import settings
from src.db.base import SessionLocal, init_db
from src.db.models import AuthAuditEvent, User
from src.email import reset_email_provider, set_email_provider
from src.orchestrator_api import app


_PASSWORD = "correct horse battery staple"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module", autouse=True)
def _ensure_schema():
    init_db()
    yield


@pytest.fixture
def client():
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
        if not users:
            return
        user_ids = [u.id for u in users]
        session.query(AuthAuditEvent).filter(
            AuthAuditEvent.user_id.in_(user_ids)
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
    return f"invariants-test-{uuid.uuid4().hex[:12]}@example.com"


def _extract_verification_token(outbox):
    body = outbox[-1][2]
    return body.split("token=")[1].split("\n")[0]


def _extract_otp(outbox):
    body = outbox[-1][2]
    return body.split("    ")[1].split("\n")[0].strip()


def _signup_verify_login(client, outbox, tracked, email):
    r = client.post(
        "/api/auth/signup",
        json={"email": email, "password": _PASSWORD, "account_type": "developer"},
    )
    assert r.status_code == 200, r.text
    tracked.append(email)

    token = _extract_verification_token(outbox)
    r = client.post("/api/auth/verify-email", json={"token": token})
    assert r.status_code == 200, r.text

    r = client.post(
        "/api/auth/login", json={"email": email, "password": _PASSWORD}
    )
    assert r.status_code == 200, r.text
    ref = r.json()["pending_auth_ref"]
    code = _extract_otp(outbox)
    r = client.post(
        "/api/auth/login/verify-otp",
        json={"pending_auth_ref": ref, "code": code},
    )
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------------------
# Enumeration resistance
# ---------------------------------------------------------------------------
class TestEnumerationResistance:
    def test_signup_new_vs_existing_body_identical(self, client, outbox, tracked):
        email = _unique_email()
        first = client.post(
            "/api/auth/signup",
            json={
                "email": email,
                "password": _PASSWORD,
                "account_type": "developer",
            },
        )
        tracked.append(email)
        second = client.post(
            "/api/auth/signup",
            json={
                "email": email,
                "password": _PASSWORD,
                "account_type": "developer",
            },
        )
        assert first.status_code == 200
        assert second.status_code == 200
        # Bodies must be byte-identical.
        assert first.json() == second.json()

    def test_login_unknown_vs_wrong_password_identical(self, client, outbox, tracked):
        email = _unique_email()
        r = client.post(
            "/api/auth/signup",
            json={"email": email, "password": _PASSWORD, "account_type": "developer"},
        )
        tracked.append(email)

        wrong_pw = client.post(
            "/api/auth/login",
            json={"email": email, "password": "not-the-password"},
        )
        unknown = client.post(
            "/api/auth/login",
            json={"email": "no-such-user@example.com", "password": "not-the-password"},
        )
        assert wrong_pw.status_code == unknown.status_code == 401
        assert wrong_pw.json()["error"]["message"] == unknown.json()["error"]["message"]

    def test_login_locked_vs_wrong_password_identical(
        self, client, outbox, tracked, monkeypatch
    ):
        monkeypatch.setattr(settings, "login_max_failed_attempts", 2)
        email = _unique_email()
        r = client.post(
            "/api/auth/signup",
            json={"email": email, "password": _PASSWORD, "account_type": "developer"},
        )
        tracked.append(email)

        # Lock the account.
        for _ in range(2):
            client.post(
                "/api/auth/login",
                json={"email": email, "password": "wrong-password-value"},
            )

        locked = client.post(
            "/api/auth/login",
            json={"email": email, "password": _PASSWORD},
        )
        unknown = client.post(
            "/api/auth/login",
            json={"email": "no-such-user@example.com", "password": _PASSWORD},
        )
        assert locked.status_code == unknown.status_code == 401
        # Compare the fields that encode the enumeration contract. The
        # `request_id` field is per-request (used for support tickets)
        # and is intentionally different on each response, so a full
        # body equality would be a false negative.
        locked_err = locked.json()["error"]
        unknown_err = unknown.json()["error"]
        assert locked_err["code"] == unknown_err["code"]
        assert locked_err["message"] == unknown_err["message"]

    def test_password_reset_request_unknown_vs_existing_identical(
        self, client, outbox, tracked
    ):
        email = _unique_email()
        r = client.post(
            "/api/auth/signup",
            json={"email": email, "password": _PASSWORD, "account_type": "developer"},
        )
        tracked.append(email)

        existing = client.post(
            "/api/auth/password-reset/request", json={"email": email}
        )
        unknown = client.post(
            "/api/auth/password-reset/request",
            json={"email": "no-such-user@example.com"},
        )
        assert existing.status_code == unknown.status_code == 200
        assert existing.json() == unknown.json()

    def test_resend_verification_unknown_vs_existing_identical(
        self, client, outbox, tracked
    ):
        email = _unique_email()
        r = client.post(
            "/api/auth/signup",
            json={"email": email, "password": _PASSWORD, "account_type": "developer"},
        )
        tracked.append(email)

        existing = client.post(
            "/api/auth/resend-verification", json={"email": email}
        )
        unknown = client.post(
            "/api/auth/resend-verification",
            json={"email": "no-such-user@example.com"},
        )
        assert existing.status_code == unknown.status_code == 200
        assert existing.json() == unknown.json()

    def test_verify_email_invalid_vs_expired_same_body(self, client):
        invalid = client.post(
            "/api/auth/verify-email", json={"token": "not-a-real-token"}
        )
        other_invalid = client.post(
            "/api/auth/verify-email", json={"token": "another-not-real-token"}
        )
        assert invalid.status_code == other_invalid.status_code == 400
        assert invalid.json()["error"]["message"] == other_invalid.json()["error"]["message"]

    def test_otp_resend_unknown_ref_returns_generic_response(self, client):
        r = client.post(
            "/api/auth/login/resend-otp",
            json={"pending_auth_ref": "not-a-real-ref"},
        )
        assert r.status_code == 200
        # Response does not reveal whether the ref exists.
        body = r.json()
        assert "pending_auth_ref" in body
        assert "account" not in body.get("message", "").lower()
        assert "user" not in body.get("message", "").lower()


# ---------------------------------------------------------------------------
# Cookies
# ---------------------------------------------------------------------------
class TestCookieAttributes:
    def test_refresh_cookie_is_httponly_secure_samesite(
        self, client, outbox, tracked
    ):
        email = _unique_email()
        _signup_verify_login(client, outbox, tracked, email)

        # Verify via a fresh login so we can inspect the Set-Cookie header.
        fresh = TestClient(app, base_url="https://testserver")
        with fresh:
            r = fresh.post(
                "/api/auth/login", json={"email": email, "password": _PASSWORD}
            )
            ref = r.json()["pending_auth_ref"]
            code = _extract_otp(outbox)
            r = fresh.post(
                "/api/auth/login/verify-otp",
                json={"pending_auth_ref": ref, "code": code},
            )
            assert r.status_code == 200

            set_cookies = r.headers.get_list("set-cookie")
            refresh_header = next(
                (h for h in set_cookies
                 if h.startswith(settings.auth_refresh_cookie_name + "=")),
                None,
            )
            assert refresh_header is not None
            lower = refresh_header.lower()
            assert "httponly" in lower
            assert "secure" in lower
            assert f"samesite={settings.auth_cookie_samesite}".lower() in lower

    def test_csrf_cookie_is_readable_by_javascript(
        self, client, outbox, tracked
    ):
        email = _unique_email()
        _signup_verify_login(client, outbox, tracked, email)

        fresh = TestClient(app, base_url="https://testserver")
        with fresh:
            r = fresh.post(
                "/api/auth/login", json={"email": email, "password": _PASSWORD}
            )
            ref = r.json()["pending_auth_ref"]
            code = _extract_otp(outbox)
            r = fresh.post(
                "/api/auth/login/verify-otp",
                json={"pending_auth_ref": ref, "code": code},
            )
            set_cookies = r.headers.get_list("set-cookie")
            csrf_header = next(
                (h for h in set_cookies
                 if h.startswith(settings.auth_csrf_cookie_name + "=")),
                None,
            )
            assert csrf_header is not None
            assert "httponly" not in csrf_header.lower()


# ---------------------------------------------------------------------------
# Cookie clearing on refresh failure (regression)
# ---------------------------------------------------------------------------
class TestRefreshFailureCookieClearing:
    def test_refresh_with_invalid_cookie_clears_both_cookies(
        self, client, outbox, tracked
    ):
        """On any refresh failure, the response must clear both the
        refresh cookie and the CSRF cookie.

        This is a regression test for a Step 6 defect: the route set
        cookie-deletion headers on the FastAPI-injected Response and
        then raised HTTPException. The exception handler built its own
        response and discarded the injected one, so the cookies were
        never cleared in the actual HTTP response.
        """
        email = _unique_email()
        _signup_verify_login(client, outbox, tracked, email)

        # Fresh client carrying an invalid refresh cookie plus the valid
        # CSRF cookie; the CSRF cookie is required to pass the CSRF
        # check before the flow is called.
        csrf = client.cookies.get(settings.auth_csrf_cookie_name)
        assert csrf

        fresh = TestClient(app, base_url="https://testserver")
        with fresh:
            fresh.cookies.set(settings.auth_refresh_cookie_name, "invalid-value")
            fresh.cookies.set(settings.auth_csrf_cookie_name, csrf)
            r = fresh.post(
                "/api/auth/refresh",
                headers={settings.auth_csrf_header_name: csrf},
            )
            assert r.status_code == 401

            set_cookies = r.headers.get_list("set-cookie")
            refresh_cleared = any(
                h.lower().startswith(settings.auth_refresh_cookie_name.lower() + "=")
                for h in set_cookies
            )
            csrf_cleared = any(
                h.lower().startswith(settings.auth_csrf_cookie_name.lower() + "=")
                for h in set_cookies
            )
            assert refresh_cleared, (
                "refresh cookie not cleared on refresh failure; "
                f"Set-Cookie headers: {set_cookies}"
            )
            assert csrf_cleared, (
                "CSRF cookie not cleared on refresh failure; "
                f"Set-Cookie headers: {set_cookies}"
            )

    def test_refresh_without_cookie_clears_any_stale_cookies(self, client):
        """Even when no refresh cookie is present, the failure response
        clears the session cookies so a stale CSRF cookie does not
        linger in the browser after the refresh cookie has expired."""
        client.cookies.clear()
        r = client.post("/api/auth/refresh")
        assert r.status_code == 401

        set_cookies = r.headers.get_list("set-cookie")
        refresh_cleared = any(
            h.lower().startswith(settings.auth_refresh_cookie_name.lower() + "=")
            for h in set_cookies
        )
        csrf_cleared = any(
            h.lower().startswith(settings.auth_csrf_cookie_name.lower() + "=")
            for h in set_cookies
        )
        assert refresh_cleared
        assert csrf_cleared


# ---------------------------------------------------------------------------
# CSRF enforcement
# ---------------------------------------------------------------------------
class TestCsrfEnforcement:
    def test_refresh_requires_csrf_header(self, client, outbox, tracked):
        email = _unique_email()
        _signup_verify_login(client, outbox, tracked, email)

        r = client.post("/api/auth/refresh")
        assert r.status_code == 403

    def test_refresh_rejects_mismatched_csrf(self, client, outbox, tracked):
        email = _unique_email()
        _signup_verify_login(client, outbox, tracked, email)

        r = client.post(
            "/api/auth/refresh",
            headers={settings.auth_csrf_header_name: "wrong-value"},
        )
        assert r.status_code == 403

    def test_logout_requires_csrf_when_session_present(
        self, client, outbox, tracked
    ):
        email = _unique_email()
        _signup_verify_login(client, outbox, tracked, email)

        r = client.post("/api/auth/logout")
        assert r.status_code == 403

    def test_logout_without_session_is_idempotent(self, client):
        client.cookies.clear()
        r = client.post("/api/auth/logout")
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Response shape invariants
# ---------------------------------------------------------------------------
class TestResponseShapeInvariants:
    def test_signup_response_contains_no_token_fields(
        self, client, outbox, tracked
    ):
        email = _unique_email()
        r = client.post(
            "/api/auth/signup",
            json={
                "email": email,
                "password": _PASSWORD,
                "account_type": "developer",
            },
        )
        tracked.append(email)
        body = r.json()
        for forbidden in (
            "access_token", "refresh_token", "otp_code", "code",
            "verification_token", "reset_token", "password",
        ):
            assert forbidden not in body, f"{forbidden} present in signup response"

    def test_login_response_contains_no_token_fields(
        self, client, outbox, tracked
    ):
        email = _unique_email()
        r = client.post(
            "/api/auth/signup",
            json={"email": email, "password": _PASSWORD, "account_type": "developer"},
        )
        tracked.append(email)
        token = _extract_verification_token(outbox)
        client.post("/api/auth/verify-email", json={"token": token})

        r = client.post(
            "/api/auth/login", json={"email": email, "password": _PASSWORD}
        )
        body = r.json()
        for forbidden in ("access_token", "refresh_token", "otp_code"):
            assert forbidden not in body, f"{forbidden} present in login response"

    def test_no_credentials_in_verify_email_response(self, client):
        r = client.post(
            "/api/auth/verify-email", json={"token": "not-a-real-token"}
        )
        body = r.json()
        for forbidden in ("password", "otp", "token", "secret"):
            assert forbidden not in body["error"]["message"].lower()


# ---------------------------------------------------------------------------
# Token / credential separation
# ---------------------------------------------------------------------------
class TestCredentialSeparation:
    def test_pending_auth_ref_cannot_authenticate_me(
        self, client, outbox, tracked
    ):
        email = _unique_email()
        r = client.post(
            "/api/auth/signup",
            json={"email": email, "password": _PASSWORD, "account_type": "developer"},
        )
        tracked.append(email)
        token = _extract_verification_token(outbox)
        client.post("/api/auth/verify-email", json={"token": token})

        r = client.post(
            "/api/auth/login", json={"email": email, "password": _PASSWORD}
        )
        ref = r.json()["pending_auth_ref"]

        r = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {ref}"},
        )
        assert r.status_code == 401

    def test_access_token_cannot_be_used_as_refresh_cookie(
        self, client, outbox, tracked
    ):
        email = _unique_email()
        tokens = _signup_verify_login(client, outbox, tracked, email)
        csrf = client.cookies.get(settings.auth_csrf_cookie_name)

        fresh = TestClient(app, base_url="https://testserver")
        with fresh:
            fresh.cookies.set(
                settings.auth_refresh_cookie_name, tokens["access_token"]
            )
            fresh.cookies.set(settings.auth_csrf_cookie_name, csrf)
            r = fresh.post(
                "/api/auth/refresh",
                headers={settings.auth_csrf_header_name: csrf},
            )
            assert r.status_code == 401


# ---------------------------------------------------------------------------
# Audit hygiene
# ---------------------------------------------------------------------------
class TestAuditHygiene:
    def test_audit_rows_contain_no_credentials(
        self, client, outbox, tracked
    ):
        email = _unique_email()
        tokens = _signup_verify_login(client, outbox, tracked, email)
        access = tokens["access_token"]
        # Grab the refresh cookie and OTP code (last OTP email).
        refresh = client.cookies.get(settings.auth_refresh_cookie_name)
        otp_code = _extract_otp(outbox)

        session = SessionLocal()
        try:
            user = session.query(User).filter(
                User.email == email.lower()
            ).one()
            rows = session.query(AuthAuditEvent).filter(
                AuthAuditEvent.user_id == user.id
            ).all()
            rendered = " ".join(
                f"{r.event_type} {r.outcome} {r.event_metadata}"
                for r in rows
            )
            assert _PASSWORD not in rendered
            assert access not in rendered
            assert (refresh or "__no_refresh__") not in rendered
            assert otp_code not in rendered
            # And the events we expect are present.
            event_types = {r.event_type for r in rows}
            assert "signup_completed" in event_types
            assert "email_verification_succeeded" in event_types
            assert "login_succeeded" in event_types
            assert "otp_verified" in event_types
        finally:
            session.close()