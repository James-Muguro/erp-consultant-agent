"""
Tests for the authentication boundary.

Focused on the current contract of:
  * POST /api/auth/signup — returns MessageResponse; no tokens.
  * POST /api/auth/login — returns a pending-auth reference; no
    access token. Full token acquisition requires
    /api/auth/login/verify-otp (covered comprehensively by
    tests/test_auth_routes.py and tests/test_auth_lifecycle.py; the
    tests here only exercise what the boundary file specifically
    needs).
  * The JWT issued by create_access_token (structure, claims).
  * The `get_current_user` dependency — its rejection behavior for
    every malformed or invalid Authorization header.
  * Independence of authentication from authorization (application
    roles, organization membership).

Not covered here, by design:
  * Signup behavior              → tests/test_signup.py
  * /me response shape           → tests/test_auth_me.py
  * Organization-only flows      → tests/test_auth_organization_only.py
  * Password mutation            → tests/test_password_change.py
  * Profile mutation             → tests/test_account_profile.py
  * Tenant boundaries            → tests/test_tenant_boundary.py
  * Route-level permissions      → tests/test_permissions_routes.py
  * OTP flow details             → tests/test_auth_routes.py,
                                   tests/test_auth_lifecycle.py

Current implementation contracts verified against the shipped source:

  * JWT claims: `sub`, `iat`, `exp`, `jti`. No `iss`, no `aud`, no
    `nbf`, no refresh token. The decoder requires `exp` and rejects
    tokens without it.
  * The bearer scheme is `HTTPBearer(auto_error=False)`. Every failure
    path in `get_current_user` raises 401 with a `WWW-Authenticate:
    Bearer` header. Two detail strings are used: "Not authenticated"
    when the header is missing/empty or the scheme is not Bearer, and
    "Invalid or expired token" for every other rejection (bad
    signature, expired, malformed, unknown subject, non-string
    subject). The uniform message deliberately avoids distinguishing
    the cases.
  * Login failure — whether the email is unknown or the password is
    wrong — is 401 with the exact detail "Invalid email or password."
    Both cases produce the same response.
  * No disabled/inactive user model field exists, so no test covers
    that scenario.
  * Rate limits relax to `10000/minute` under pytest (`_TESTING`), so
    the tests here are not rate-limit sensitive.

No production code, migration, existing test, fixture, or
configuration is modified by this file.
"""
from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Iterator, List, Tuple

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.auth.security import create_access_token
from src.config.settings import settings
from src.db.base import SessionLocal
from src.db.models import Organization, SessionRecord, User
from src.email import reset_email_provider, set_email_provider
from src.orchestrator_api import app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_CURRENT_PW = "testpassword123"

_ALGO = settings.jwt_algorithm.strip().upper()


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


def _unique_email(prefix: str = "auth-bnd") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}@example.com"


def _signup_and_authenticate(
    client: TestClient,
    email: str,
    account_type: str = "functional_consultant",
    organization_name: str | None = None,
    password: str = _CURRENT_PW,
) -> str:
    """Complete the full authentication flow and return an access token.

    The flow is: signup → verify-email → login → verify-otp. The email
    abstraction is mocked for the duration so no SMTP connection is
    attempted.
    """
    captured: List[Tuple[str, str, str]] = []

    def _capture(to: str, subject: str, body: str) -> None:
        captured.append((to, subject, body))

    set_email_provider(_capture)
    try:
        payload = {
            "email": email,
            "password": password,
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
            json={"email": email, "password": password},
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


def _decode(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret_key, algorithms=[_ALGO])


def _craft_token(
    payload: dict,
    *,
    secret: str | None = None,
    algorithm: str | None = None,
) -> str:
    return jwt.encode(
        payload,
        secret if secret is not None else settings.jwt_secret_key,
        algorithm=algorithm if algorithm is not None else _ALGO,
    )


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
# A. Login endpoint — pending-auth contract
# ===========================================================================
class TestLoginEndpoint:
    def test_login_with_valid_credentials_returns_pending_auth_ref(
        self, client, created_users,
    ):
        """Login success now returns a pending-auth reference, NOT an
        access token. Token acquisition is a separate step handled by
        /api/auth/login/verify-otp. This test locks in the two-step
        contract at the login endpoint."""
        email = _unique_email()
        created_users.emails.append(email)

        captured: List[Tuple[str, str, str]] = []
        set_email_provider(lambda t, s, b: captured.append((t, s, b)))
        try:
            # Full flow up to login: signup + verify-email, then call
            # login.
            r = client.post(
                "/api/auth/signup",
                json={
                    "email": email,
                    "password": _CURRENT_PW,
                    "account_type": "functional_consultant",
                },
            )
            assert r.status_code == 200, r.text
            raw_verify = (
                captured[-1][2].split("token=")[1].split("\n")[0]
            )
            r = client.post(
                "/api/auth/verify-email", json={"token": raw_verify}
            )
            assert r.status_code == 200, r.text

            r = client.post(
                "/api/auth/login",
                json={"email": email, "password": _CURRENT_PW},
            )
        finally:
            reset_email_provider()

        assert r.status_code == 200, r.text
        body = r.json()
        assert "pending_auth_ref" in body
        assert "expires_in_minutes" in body
        assert "message" in body
        # The response MUST NOT contain a token.
        assert "access_token" not in body
        assert "refresh_token" not in body

    def test_login_email_is_case_insensitive(
        self, client, created_users,
    ):
        email = _unique_email()
        created_users.emails.append(email)

        captured: List[Tuple[str, str, str]] = []
        set_email_provider(lambda t, s, b: captured.append((t, s, b)))
        try:
            r = client.post(
                "/api/auth/signup",
                json={
                    "email": email,
                    "password": _CURRENT_PW,
                    "account_type": "functional_consultant",
                },
            )
            assert r.status_code == 200
            raw_verify = (
                captured[-1][2].split("token=")[1].split("\n")[0]
            )
            client.post(
                "/api/auth/verify-email", json={"token": raw_verify}
            )

            upper = email.upper()
            r = client.post(
                "/api/auth/login",
                json={"email": upper, "password": _CURRENT_PW},
            )
        finally:
            reset_email_provider()

        assert r.status_code == 200, r.text

    def test_login_with_nonexistent_email_returns_401(
        self, client,
    ):
        r = client.post(
            "/api/auth/login",
            json={
                "email": f"nobody-{uuid.uuid4().hex}@example.com",
                "password": "anypassword12345",
            },
        )
        assert r.status_code == 401, r.text
        body = r.json()
        assert body["error"]["code"] == 401
        assert body["error"]["message"] == "Invalid email or password."

    def test_login_with_wrong_password_returns_401(
        self, client, created_users,
    ):
        email = _unique_email()
        created_users.emails.append(email)

        # Sign up + verify so the account exists in a login-ready state.
        captured: List[Tuple[str, str, str]] = []
        set_email_provider(lambda t, s, b: captured.append((t, s, b)))
        try:
            r = client.post(
                "/api/auth/signup",
                json={
                    "email": email,
                    "password": _CURRENT_PW,
                    "account_type": "functional_consultant",
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
                json={"email": email, "password": "wrong-password-123456"},
            )
        finally:
            reset_email_provider()

        assert r.status_code == 401, r.text
        body = r.json()
        assert body["error"]["code"] == 401
        assert body["error"]["message"] == "Invalid email or password."

    def test_login_with_empty_password_returns_422(self, client):
        r = client.post(
            "/api/auth/login",
            json={"email": "someone@example.com", "password": ""},
        )
        assert r.status_code == 422, r.text

    def test_login_with_missing_password_field_returns_422(self, client):
        r = client.post(
            "/api/auth/login",
            json={"email": "someone@example.com"},
        )
        assert r.status_code == 422, r.text

    def test_login_with_invalid_email_format_returns_422(self, client):
        r = client.post(
            "/api/auth/login",
            json={"email": "not-an-email", "password": "anypassword12345"},
        )
        assert r.status_code == 422, r.text


# ===========================================================================
# B. JWT structure
# ===========================================================================
class TestJWTStructure:
    def test_token_carries_expected_claims(self, client, created_users):
        """The token issued by verify-otp carries sub, iat, exp, and
        jti. No iss, aud, nbf, or refresh-token fields are present."""
        email = _unique_email()
        created_users.emails.append(email)
        token = _signup_and_authenticate(client, email)

        decoded = _decode(token)
        assert "sub" in decoded
        assert "iat" in decoded
        assert "exp" in decoded
        assert "jti" in decoded
        for absent in ("iss", "aud", "nbf", "refresh_token"):
            assert absent not in decoded

    def test_token_subject_is_user_id(self, client, created_users):
        email = _unique_email()
        created_users.emails.append(email)
        token = _signup_and_authenticate(client, email)
        user_id = _user_id_for_email(email)

        decoded = _decode(token)
        assert decoded["sub"] == user_id

    def test_token_exp_is_in_the_future(self, client, created_users):
        email = _unique_email()
        created_users.emails.append(email)
        token = _signup_and_authenticate(client, email)

        decoded = _decode(token)
        exp = decoded["exp"]
        assert isinstance(exp, (int, float))
        now_ts = datetime.now(timezone.utc).timestamp()
        assert exp > now_ts + 60


# ===========================================================================
# C. Authentication dependency boundary
# ===========================================================================
class TestAuthDependencyBoundary:
    def test_missing_authorization_header_returns_401(self, client):
        r = client.get("/api/auth/me")
        assert r.status_code == 401, r.text
        assert r.json()["error"]["message"] == "Not authenticated"

    def test_empty_authorization_header_returns_401(self, client):
        r = client.get("/api/auth/me", headers={"Authorization": ""})
        assert r.status_code == 401, r.text
        assert r.json()["error"]["message"] == "Not authenticated"

    def test_non_bearer_scheme_returns_401(self, client):
        r = client.get(
            "/api/auth/me",
            headers={"Authorization": "Basic dXNlcjpwYXNz"},
        )
        assert r.status_code == 401, r.text
        assert r.json()["error"]["message"] == "Not authenticated"

    def test_bare_bearer_without_credentials_returns_401(self, client):
        r = client.get("/api/auth/me", headers={"Authorization": "Bearer"})
        assert r.status_code == 401, r.text
        assert r.json()["error"]["message"] == "Not authenticated"

    def test_malformed_jwt_returns_401(self, client):
        r = client.get(
            "/api/auth/me",
            headers={"Authorization": "Bearer not-a-jwt"},
        )
        assert r.status_code == 401, r.text
        assert r.json()["error"]["message"] == "Invalid or expired token"

    def test_token_with_invalid_signature_returns_401(self, client):
        wrong_secret = "wrong-secret-key-that-is-at-least-32-characters-long"
        payload = {
            "sub": "any-user-id",
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc) + timedelta(minutes=10),
            "jti": uuid.uuid4().hex,
        }
        bad_token = _craft_token(payload, secret=wrong_secret)

        r = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {bad_token}"},
        )
        assert r.status_code == 401, r.text
        assert r.json()["error"]["message"] == "Invalid or expired token"

    def test_expired_token_returns_401(self, client, created_users):
        email = _unique_email()
        created_users.emails.append(email)
        _signup_and_authenticate(client, email)
        user_id = _user_id_for_email(email)

        expired = create_access_token(user_id, expires_minutes=-60)
        r = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {expired}"},
        )
        assert r.status_code == 401, r.text
        assert r.json()["error"]["message"] == "Invalid or expired token"

    def test_token_with_unknown_subject_returns_401(self, client):
        orphan_token = create_access_token(f"orphan-{uuid.uuid4().hex}")
        r = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {orphan_token}"},
        )
        assert r.status_code == 401, r.text
        assert r.json()["error"]["message"] == "Invalid or expired token"

    def test_token_with_non_string_subject_returns_401(self, client):
        payload = {
            "sub": 12345,
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc) + timedelta(minutes=10),
        }
        bad_token = _craft_token(payload)

        r = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {bad_token}"},
        )
        assert r.status_code == 401, r.text
        assert r.json()["error"]["message"] == "Invalid or expired token"

    def test_token_after_account_deletion_returns_401(
        self, client, created_users,
    ):
        email = _unique_email()
        created_users.emails.append(email)
        token = _signup_and_authenticate(client, email)

        assert client.get(
            "/api/auth/me", headers=_headers(token),
        ).status_code == 200

        r = client.delete("/api/auth/account", headers=_headers(token))
        assert r.status_code == 200, r.text
        assert r.json()["deleted"] is True

        r = client.get("/api/auth/me", headers=_headers(token))
        assert r.status_code == 401, r.text
        assert r.json()["error"]["message"] == "Invalid or expired token"


# ===========================================================================
# D. Error envelope and headers
# ===========================================================================
class TestAuthErrorEnvelope:
    def test_401_response_uses_application_error_envelope(self, client):
        r = client.get("/api/auth/me")
        assert r.status_code == 401
        body = r.json()
        assert "error" in body
        assert body["error"]["code"] == 401
        assert "message" in body["error"]
        assert "request_id" in body["error"]

    def test_401_response_carries_www_authenticate_header(self, client):
        r = client.get("/api/auth/me")
        assert r.status_code == 401
        assert r.headers.get("WWW-Authenticate") == "Bearer"


# ===========================================================================
# E. Authentication independence from roles / membership
# ===========================================================================
class TestAuthIndependenceFromRoles:
    def test_login_succeeds_for_every_role_and_membership_configuration(
        self, client, created_users,
    ):
        """Login is orthogonal to application roles and organization
        membership: a user with a role, and a user with no application
        role but an organization membership, both reach the MFA step.

        Both flows stop at the pending-auth response, since this file's
        purpose is the authentication boundary, not the full OTP flow
        (covered elsewhere)."""
        fc_email = _unique_email("fc")
        created_users.emails.append(fc_email)

        captured: List[Tuple[str, str, str]] = []
        set_email_provider(lambda t, s, b: captured.append((t, s, b)))
        try:
            # (a) User with an application role.
            r = client.post(
                "/api/auth/signup",
                json={
                    "email": fc_email,
                    "password": _CURRENT_PW,
                    "account_type": "functional_consultant",
                },
            )
            assert r.status_code == 200
            raw_verify = (
                captured[-1][2].split("token=")[1].split("\n")[0]
            )
            client.post(
                "/api/auth/verify-email", json={"token": raw_verify}
            )

            r1 = client.post(
                "/api/auth/login",
                json={"email": fc_email, "password": _CURRENT_PW},
            )
            assert r1.status_code == 200, r1.text
            assert "pending_auth_ref" in r1.json()

            # (b) Organization-only user with no application role.
            org_email = _unique_email("orgonly")
            created_users.emails.append(org_email)
            r = client.post(
                "/api/auth/signup",
                json={
                    "email": org_email,
                    "password": _CURRENT_PW,
                    "account_type": "organization",
                    "organization_name": "Auth Boundary Test Org",
                },
            )
            assert r.status_code == 200
            raw_verify = (
                captured[-1][2].split("token=")[1].split("\n")[0]
            )
            client.post(
                "/api/auth/verify-email", json={"token": raw_verify}
            )

            r2 = client.post(
                "/api/auth/login",
                json={"email": org_email, "password": _CURRENT_PW},
            )
        finally:
            reset_email_provider()

        assert r2.status_code == 200, r2.text
        assert "pending_auth_ref" in r2.json()

        # Both users have completed the login flow up to (but not
        # including) OTP verification. Token-level authentication is
        # covered by _signup_and_authenticate and the OTP-specific
        # suites.