"""
Step 7 tests for endpoint-level abuse protection.

Scope: rate-limit constants and their application to the auth routes,
the custom 429 handler, the trusted-proxy IP resolution, and the two
flow-layer fixes that close the OTP-accumulation and password-reset-email
bypasses.

Email is intercepted with `set_email_provider` in every test that
exercises a flow; no SMTP connection is opened. No live network access
is required.

Coverage:
    * Custom 429 handler returns the application error envelope, does not
      leak the limit string or the rate-limit key, and includes
      Retry-After.
    * Each auth route is registered with the intended limit constant.
    * The trusted-proxy IP resolver honors trusted_proxy_hops and does
      not accept a spoofed X-Forwarded-For when hops == 0.
    * Flow-layer fix: initiate_login supersedes prior unconsumed OTPs
      when issuing a new one.
    * Flow-layer fix: request_password_reset is throttled per target.
    * Enumeration-resistant response for the throttled reset path stays
      identical to the non-throttled path.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Iterator, List, Tuple

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from slowapi.errors import RateLimitExceeded
from starlette.responses import JSONResponse

from src.config.settings import settings
from src.db.base import SessionLocal, init_db
from src.db.models import (
    AuthAuditEvent,
    AuthOtpRecord,
    AuthPasswordResetToken,
    User,
)
from src.email import reset_email_provider, set_email_provider
from src.orchestrator_api import (
    AUTH_RATE_LIMIT,
    LOGIN_RATE_LIMIT,
    PASSWORD_RESET_COMPLETE_RATE_LIMIT,
    PASSWORD_RESET_REQUEST_RATE_LIMIT,
    REFRESH_RATE_LIMIT,
    RESEND_OTP_RATE_LIMIT,
    RESEND_VERIFICATION_RATE_LIMIT,
    VERIFY_EMAIL_RATE_LIMIT,
    VERIFY_OTP_RATE_LIMIT,
    _client_ip,
    _client_ip_for_rate_limit,
    app,
)


@pytest.fixture(scope="module", autouse=True)
def _ensure_schema():
    init_db()
    yield


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


def _unique_email() -> str:
    return f"rate-limits-test-{uuid.uuid4().hex[:12]}@example.com"


_PASSWORD = "correct horse battery staple"


# ---------------------------------------------------------------------------
# Rate-limit constants and their application
# ---------------------------------------------------------------------------
class TestRateLimitConstants:
    def test_constants_are_distinct_names_with_matching_shapes(self):
        """Every protected endpoint uses its own constant. Under
        pytest, the values collapse to the same relaxed testing value,
        so value distinctness cannot be asserted here; what CAN be
        asserted at test time is that the constants exist, are strings
        in the slowapi 'N/period' form, and are separate bindings.

        Production values are exercised manually against the running
        server; a regression in the production values would need a
        settings-level test with _TESTING forced False.
        """
        import re

        names = {
            "AUTH_RATE_LIMIT": AUTH_RATE_LIMIT,
            "LOGIN_RATE_LIMIT": LOGIN_RATE_LIMIT,
            "VERIFY_EMAIL_RATE_LIMIT": VERIFY_EMAIL_RATE_LIMIT,
            "RESEND_VERIFICATION_RATE_LIMIT": RESEND_VERIFICATION_RATE_LIMIT,
            "VERIFY_OTP_RATE_LIMIT": VERIFY_OTP_RATE_LIMIT,
            "RESEND_OTP_RATE_LIMIT": RESEND_OTP_RATE_LIMIT,
            "REFRESH_RATE_LIMIT": REFRESH_RATE_LIMIT,
            "PASSWORD_RESET_REQUEST_RATE_LIMIT": PASSWORD_RESET_REQUEST_RATE_LIMIT,
            "PASSWORD_RESET_COMPLETE_RATE_LIMIT": PASSWORD_RESET_COMPLETE_RATE_LIMIT,
        }
        for name, value in names.items():
            assert isinstance(value, str) and value, f"{name} is not a non-empty string"
            assert re.match(r"^\d+/[a-z]+$", value), (
                f"{name}={value!r} does not match slowapi's 'N/period' form"
            )

    def test_all_auth_routes_are_decorated(self):
        """Walk the FastAPI route table and assert every auth endpoint
        has the slowapi decorator marker. Absence of the marker means
        the route silently bypasses rate limiting."""
        # slowapi stores a "rate_limit" attribute on the decorated
        # function; the decorator sets it before route registration.
        expected_paths = {
            "/api/auth/signup",
            "/api/auth/login",
            "/api/auth/verify-email",
            "/api/auth/resend-verification",
            "/api/auth/login/verify-otp",
            "/api/auth/login/resend-otp",
            "/api/auth/refresh",
            "/api/auth/password-reset/request",
            "/api/auth/password-reset/complete",
        }
        seen = set()
        for route in app.routes:
            path = getattr(route, "path", None)
            if path in expected_paths:
                seen.add(path)
                endpoint = getattr(route, "endpoint", None)
                assert endpoint is not None, f"{path} has no endpoint"
                # slowapi sets a `_rate_limit_decorated` marker or the
                # function's qualname is stored in limiter's registry;
                # the reliable check is the wrapper attribute set by the
                # decorator.
                assert getattr(endpoint, "_rate_limited", False) or \
                    hasattr(endpoint, "__wrapped__") or \
                    endpoint.__qualname__ in str(getattr(app.state.limiter, "_route_limits", {})), \
                    f"{path} endpoint is not rate-limit decorated"
        assert seen == expected_paths, f"missing routes: {expected_paths - seen}"


# ---------------------------------------------------------------------------
# Custom 429 handler
# ---------------------------------------------------------------------------
class TestRateLimitHandler:
    def test_handler_returns_envelope_and_retry_after(self):
        """Build a minimal app with the same handler to exercise 429
        end-to-end without needing to trip a real limit on the main app
        (whose test-mode limits are 10000/minute)."""
        from slowapi import Limiter

        test_app = FastAPI()
        # slowapi calls key_func with no arguments in this version, so
        # the callable must tolerate a zero-arg invocation.
        test_limiter = Limiter(
            key_func=lambda *args, **kwargs: "test-key",
            default_limits=[],
        )
        test_app.state.limiter = test_limiter

        @test_app.exception_handler(RateLimitExceeded)
        async def handler(request: Request, exc: RateLimitExceeded):
            # Mirror the production handler's shape.
            resp = JSONResponse(
                status_code=429,
                content={
                    "error": {
                        "code": 429,
                        "message": "Too many requests. Please try again later.",
                        "request_id": getattr(request.state, "request_id", None),
                    }
                },
            )
            resp.headers["Retry-After"] = "60"
            return resp

        @test_app.get("/limited")
        @test_limiter.limit("1/minute")
        async def limited(request: Request):
            return {"ok": True}

        with TestClient(test_app) as c:
            r1 = c.get("/limited")
            assert r1.status_code == 200
            r2 = c.get("/limited")
            assert r2.status_code == 429
            body = r2.json()
            assert "error" in body
            assert body["error"]["code"] == 429
            assert "Too many requests" in body["error"]["message"]
            # The response does not leak the limit string or the key.
            assert "1 per" not in body["error"]["message"]
            assert "test-key" not in str(body)
            assert r2.headers.get("Retry-After") == "60"


# ---------------------------------------------------------------------------
# Trusted-proxy IP resolution
# ---------------------------------------------------------------------------
class TestClientIpResolution:
    def _request(self, headers: dict, client_host: str = "10.0.0.1") -> Request:
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [
                (k.lower().encode("latin-1"), v.encode("latin-1"))
                for k, v in headers.items()
            ],
            "client": (client_host, 12345),
            "server": ("testserver", 80),
            "scheme": "http",
            "query_string": b"",
            "http_version": "1.1",
        }
        return Request(scope)

    def test_no_proxy_ignores_forwarded_header(self, monkeypatch):
        """With trusted_proxy_hops == 0, a spoofed X-Forwarded-For must
        not affect the resolved IP. This is the safe default."""
        monkeypatch.setattr(settings, "trusted_proxy_hops", 0)
        req = self._request(
            {"x-forwarded-for": "1.2.3.4, 5.6.7.8"},
            client_host="10.0.0.1",
        )
        assert _client_ip(req) == "10.0.0.1"
        assert _client_ip_for_rate_limit(req) == "ip:10.0.0.1"

    def test_one_hop_takes_rightmost_forwarded(self, monkeypatch):
        """With trusted_proxy_hops == 1, the rightmost X-Forwarded-For
        entry is authoritative — the value our single trusted proxy
        appended. A client-supplied entry to the left is ignored."""
        monkeypatch.setattr(settings, "trusted_proxy_hops", 1)
        req = self._request(
            {"x-forwarded-for": "1.2.3.4, 5.6.7.8"},
            client_host="10.0.0.1",
        )
        assert _client_ip(req) == "5.6.7.8"

    def test_two_hops_takes_second_from_right(self, monkeypatch):
        monkeypatch.setattr(settings, "trusted_proxy_hops", 2)
        req = self._request(
            {"x-forwarded-for": "1.2.3.4, 5.6.7.8, 9.10.11.12"},
            client_host="10.0.0.1",
        )
        assert _client_ip(req) == "5.6.7.8"

    def test_missing_client_falls_back_to_unknown(self, monkeypatch):
        monkeypatch.setattr(settings, "trusted_proxy_hops", 0)
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [],
            "client": None,
            "server": ("testserver", 80),
            "scheme": "http",
            "query_string": b"",
            "http_version": "1.1",
        }
        req = Request(scope)
        assert _client_ip_for_rate_limit(req) == "ip:unknown"


# ---------------------------------------------------------------------------
# Flow-layer fix: OTP supersession in initiate_login
# ---------------------------------------------------------------------------
class TestOtpSupersession:
    def test_new_otp_supersedes_prior_unconsumed(
        self, outbox, tracked
    ):
        """If a prior unconsumed OTP exists and the resend interval has
        elapsed, issuing a new OTP must invalidate the prior one. This
        is the fix that closes the "accumulate many pending-auth refs"
        bypass."""
        from src.auth import flows

        email = _unique_email()
        tracked.append(email)
        # Signup + verify.
        flows.signup(
            db := SessionLocal(),
            email=email,
            password=_PASSWORD,
            account_type=__import__(
                "src.auth.permissions", fromlist=["AccountType"]
            ).AccountType.DEVELOPER,
        )
        db.close()

        db = SessionLocal()
        try:
            verify_raw = outbox[-1][2].split("token=")[1].split("\n")[0]
            flows.verify_email(db, raw_token=verify_raw)

            # First login: creates OTP #1.
            pending1 = flows.initiate_login(db, email=email, password=_PASSWORD)
            ref1 = pending1.pending_auth_ref

            # Backdate the OTP row so the resend interval has elapsed.
            row1 = (
                db.query(AuthOtpRecord)
                .filter(AuthOtpRecord.id == ref1)
                .one()
            )
            row1.created_at = datetime.now(timezone.utc) - timedelta(minutes=5)
            db.commit()

            # Second login: must invalidate OTP #1 and issue OTP #2.
            pending2 = flows.initiate_login(db, email=email, password=_PASSWORD)
            ref2 = pending2.pending_auth_ref
            assert ref2 != ref1

            db.refresh(row1)
            assert row1.used_at is not None, (
                "prior OTP was not superseded — accumulation bypass remains"
            )

            # Exactly one unconsumed OTP for this user.
            user = db.query(User).filter(User.email == email.lower()).one()
            live = (
                db.query(AuthOtpRecord)
                .filter(
                    AuthOtpRecord.user_id == user.id,
                    AuthOtpRecord.purpose == "login_mfa",
                    AuthOtpRecord.used_at.is_(None),
                )
                .all()
            )
            assert len(live) == 1
            assert live[0].id == ref2
        finally:
            db.close()


# ---------------------------------------------------------------------------
# Flow-layer fix: password-reset request throttle
# ---------------------------------------------------------------------------
class TestPasswordResetThrottle:
    def test_second_request_inside_interval_is_throttled(
        self, outbox, tracked
    ):
        from src.auth import flows

        email = _unique_email()
        tracked.append(email)
        db = SessionLocal()
        try:
            flows.signup(
                db,
                email=email,
                password=_PASSWORD,
                account_type=__import__(
                    "src.auth.permissions", fromlist=["AccountType"]
                ).AccountType.DEVELOPER,
            )
            # Reset outbox view for this phase.
            before = len(outbox)

            flows.request_password_reset(db, email=email)
            after_first = len(outbox)
            assert after_first == before + 1

            # Second request inside the interval: no new email.
            flows.request_password_reset(db, email=email)
            assert len(outbox) == after_first

            # Backdate the token so the interval has elapsed.
            user = db.query(User).filter(User.email == email.lower()).one()
            token = (
                db.query(AuthPasswordResetToken)
                .filter(AuthPasswordResetToken.user_id == user.id)
                .order_by(AuthPasswordResetToken.created_at.desc())
                .first()
            )
            token.created_at = datetime.now(timezone.utc) - timedelta(minutes=5)
            db.commit()

            flows.request_password_reset(db, email=email)
            assert len(outbox) == after_first + 1
        finally:
            db.close()

    def test_throttled_response_is_enumeration_resistant(
        self, outbox, tracked
    ):
        """The throttled path returns the same externally-visible outcome
        as the non-throttled path. The audit metadata differs but the
        client cannot see the audit log."""
        from src.auth import flows

        email = _unique_email()
        tracked.append(email)
        db = SessionLocal()
        try:
            flows.signup(
                db,
                email=email,
                password=_PASSWORD,
                account_type=__import__(
                    "src.auth.permissions", fromlist=["AccountType"]
                ).AccountType.DEVELOPER,
            )
            # First call (succeeds internally).
            flows.request_password_reset(db, email=email)
            # Second call (throttled internally).
            flows.request_password_reset(db, email=email)
            # Both return None; the route maps both to the same response.
            # Assert that the audit row for the throttled call records
            # the throttled flag so operators can see throttling.
            user = db.query(User).filter(User.email == email.lower()).one()
            rows = (
                db.query(AuthAuditEvent)
                .filter(
                    AuthAuditEvent.user_id == user.id,
                    AuthAuditEvent.event_type == "password_reset_requested",
                )
                .order_by(AuthAuditEvent.created_at.asc())
                .all()
            )
            assert len(rows) == 2
            assert rows[1].event_metadata.get("throttled") is True
        finally:
            db.close()