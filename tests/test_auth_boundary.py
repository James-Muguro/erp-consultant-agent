"""
Tests for the authentication boundary.

Focused on the current contract of:
  * POST /api/auth/login
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
  * Login error for any credential failure is 401 with the exact
    detail "Incorrect email or password" — identical for unknown email
    and wrong password, matching the timing-resistant design of
    `authenticate_user`.
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
from typing import Iterator, List

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.auth.security import create_access_token
from src.config.settings import settings
from src.db.base import SessionLocal
from src.db.models import Organization, SessionRecord, User
from src.orchestrator_api import app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
# Fixed passwords for the file. Chosen to satisfy the signup schema
# (>= 12 chars, not on the blocklist, does not contain the hex local
# part of any email produced by `_unique_email`).
_CURRENT_PW = "testpassword123"

# The algorithm name is normalized in `src/auth/security.py` before use
# (`.strip().upper()`). Mirror that here so the crafted JWTs below sign
# and verify under exactly the algorithm the app expects.
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


def _signup(
    client: TestClient,
    email: str,
    account_type: str = "functional_consultant",
    organization_name: str | None = None,
) -> str:
    """Sign up a user with the given account type and return the access
    token. `organization_name` is only required for the organization
    account type, and is passed through when supplied."""
    payload = {
        "email": email,
        "password": _CURRENT_PW,
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


def _decode(token: str) -> dict:
    """Decode with the app's own secret and algorithm. Only used to
    inspect claims of tokens the app issued."""
    return jwt.decode(token, settings.jwt_secret_key, algorithms=[_ALGO])


def _craft_token(
    payload: dict,
    *,
    secret: str | None = None,
    algorithm: str | None = None,
) -> str:
    """Sign an arbitrary payload. Used to construct tokens the app
    would not issue itself (wrong signature, non-string subject)."""
    return jwt.encode(
        payload,
        secret if secret is not None else settings.jwt_secret_key,
        algorithm=algorithm if algorithm is not None else _ALGO,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def client():
    """TestClient entered as a context manager so the lifespan runs.
    raise_server_exceptions=False so a 500 from an unexpected path
    surfaces as a response rather than a raised exception."""
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


class _Registry:
    def __init__(self):
        self.emails: List[str] = []


@pytest.fixture
def created_users():
    """Track emails created during a test and delete their rows on
    teardown. Mirrors the cleanup pattern used by the other integration
    test files."""
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
# A. Login endpoint
# ===========================================================================
class TestLoginEndpoint:
    def test_login_with_valid_credentials_returns_token(
        self, client, created_users,
    ):
        """Login success returns the same TokenResponse shape as signup:
        access_token, token_type='bearer', expires_in_minutes."""
        email = _unique_email()
        created_users.emails.append(email)
        _signup(client, email)

        r = client.post(
            "/api/auth/login",
            json={"email": email, "password": _CURRENT_PW},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert "access_token" in body
        assert body["token_type"] == "bearer"
        assert isinstance(body["expires_in_minutes"], int)
        assert body["expires_in_minutes"] > 0

    def test_login_email_is_case_insensitive(
        self, client, created_users,
    ):
        """The schema lowercases the email on login, matching signup."""
        email = _unique_email()
        created_users.emails.append(email)
        _signup(client, email)

        # Uppercase the local part and the domain.
        upper = email.upper()
        r = client.post(
            "/api/auth/login",
            json={"email": upper, "password": _CURRENT_PW},
        )
        assert r.status_code == 200, r.text

    def test_login_with_nonexistent_email_returns_401(
        self, client,
    ):
        """Unknown email produces the same 401 detail as a wrong
        password — the endpoint never reveals whether an email is
        registered."""
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
        assert body["error"]["message"] == "Incorrect email or password"

    def test_login_with_wrong_password_returns_401(
        self, client, created_users,
    ):
        email = _unique_email()
        created_users.emails.append(email)
        _signup(client, email)

        r = client.post(
            "/api/auth/login",
            json={"email": email, "password": "wrong-password-123456"},
        )
        assert r.status_code == 401, r.text
        body = r.json()
        assert body["error"]["code"] == 401
        assert body["error"]["message"] == "Incorrect email or password"

    def test_login_with_empty_password_returns_422(self, client):
        """`LoginRequest.password` has `min_length=1`; an empty string
        fails at the schema layer with 422 before any DB lookup."""
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
        """`LoginRequest.email` is `EmailStr`; a malformed value fails
        at the schema layer."""
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
        """The issued token carries sub, iat, exp, and jti. No iss,
        aud, nbf, or refresh-token fields are present — the current
        implementation does not issue them."""
        email = _unique_email()
        created_users.emails.append(email)
        token = _signup(client, email)

        decoded = _decode(token)
        assert "sub" in decoded
        assert "iat" in decoded
        assert "exp" in decoded
        assert "jti" in decoded
        # Claims the current implementation does NOT issue. Asserting
        # absence so a future addition is a deliberate change that
        # updates this test rather than a silent behavioural shift.
        for absent in ("iss", "aud", "nbf", "refresh_token"):
            assert absent not in decoded

    def test_token_subject_is_user_id(self, client, created_users):
        email = _unique_email()
        created_users.emails.append(email)
        token = _signup(client, email)
        user_id = _user_id_for_email(email)

        decoded = _decode(token)
        assert decoded["sub"] == user_id

    def test_token_exp_is_in_the_future(self, client, created_users):
        """`exp` is a numeric timestamp set to now + the configured
        lifetime. Compare against the current wall clock with a small
        tolerance rather than asserting an exact value."""
        email = _unique_email()
        created_users.emails.append(email)
        token = _signup(client, email)

        decoded = _decode(token)
        exp = decoded["exp"]
        assert isinstance(exp, (int, float))
        now_ts = datetime.now(timezone.utc).timestamp()
        # Long enough in the future that scheduling jitter cannot make
        # this test flaky.
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
        """An empty Authorization value is treated the same as a
        missing one — the header carries no credentials."""
        r = client.get("/api/auth/me", headers={"Authorization": ""})
        assert r.status_code == 401, r.text
        assert r.json()["error"]["message"] == "Not authenticated"

    def test_non_bearer_scheme_returns_401(self, client):
        """HTTPBearer(auto_error=False) returns None for any scheme
        other than Bearer; the dependency raises 401 with the same
        "Not authenticated" message as a missing header."""
        r = client.get(
            "/api/auth/me",
            headers={"Authorization": "Basic dXNlcjpwYXNz"},
        )
        assert r.status_code == 401, r.text
        assert r.json()["error"]["message"] == "Not authenticated"

    def test_bare_bearer_without_credentials_returns_401(self, client):
        """`Authorization: Bearer` with no value is treated as a
        missing-credential case: the header is present but empty."""
        r = client.get("/api/auth/me", headers={"Authorization": "Bearer"})
        assert r.status_code == 401, r.text
        assert r.json()["error"]["message"] == "Not authenticated"

    def test_malformed_jwt_returns_401(self, client):
        """A string that is not a JWT at all (no dot-separated parts)
        fails decode; the message is the uniform token-rejection
        detail."""
        r = client.get(
            "/api/auth/me",
            headers={"Authorization": "Bearer not-a-jwt"},
        )
        assert r.status_code == 401, r.text
        assert r.json()["error"]["message"] == "Invalid or expired token"

    def test_token_with_invalid_signature_returns_401(self, client):
        """A token whose structure and claims are valid but whose
        signature was produced with a different secret is rejected
        during signature verification."""
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
        """A token whose exp is in the past is rejected. Uses
        create_access_token with a negative `expires_minutes` to
        produce a genuinely signed-but-expired token."""
        email = _unique_email()
        created_users.emails.append(email)
        _signup(client, email)
        user_id = _user_id_for_email(email)

        expired = create_access_token(user_id, expires_minutes=-60)
        r = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {expired}"},
        )
        assert r.status_code == 401, r.text
        assert r.json()["error"]["message"] == "Invalid or expired token"

    def test_token_with_unknown_subject_returns_401(self, client):
        """A valid-signed token whose subject references no user row is
        rejected. This is the same failure class as a token issued for
        a user who has since been deleted — the two scenarios are
        collapsed by the dependency."""
        orphan_token = create_access_token(f"orphan-{uuid.uuid4().hex}")
        r = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {orphan_token}"},
        )
        assert r.status_code == 401, r.text
        assert r.json()["error"]["message"] == "Invalid or expired token"

    def test_token_with_non_string_subject_returns_401(self, client):
        """A signed token whose `sub` claim is not a non-empty string
        is rejected during decode. The `sub` type check is defensive
        against tokens the API never issues."""
        payload = {
            "sub": 12345,  # int, not str
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
        """After the account is deleted via the real endpoint, the
        previously-valid token is rejected. End-to-end coverage of the
        deleted-user branch, exercised through the shipped route
        rather than a direct DB delete."""
        email = _unique_email()
        created_users.emails.append(email)
        token = _signup(client, email)

        # Sanity: the token authenticates before deletion.
        assert client.get(
            "/api/auth/me", headers=_headers(token),
        ).status_code == 200

        r = client.delete("/api/auth/account", headers=_headers(token))
        assert r.status_code == 200, r.text
        assert r.json()["deleted"] is True

        # Same token, now rejected.
        r = client.get("/api/auth/me", headers=_headers(token))
        assert r.status_code == 401, r.text
        assert r.json()["error"]["message"] == "Invalid or expired token"


# ===========================================================================
# D. Error envelope and headers
# ===========================================================================
class TestAuthErrorEnvelope:
    def test_401_response_uses_application_error_envelope(self, client):
        """Every 401 from get_current_user is wrapped by the app's
        HTTPException handler into the standard envelope:
        {"error": {"code", "message", "request_id"}}."""
        r = client.get("/api/auth/me")
        assert r.status_code == 401
        body = r.json()
        assert "error" in body
        assert body["error"]["code"] == 401
        assert "message" in body["error"]
        assert "request_id" in body["error"]

    def test_401_response_carries_www_authenticate_header(self, client):
        """RFC 6750 §3: a 401 must include `WWW-Authenticate: Bearer`
        so standards-compliant clients know which scheme is expected.
        The dependency attaches it to every 401 it raises."""
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
        """The login route and the JWT verification path are
        orthogonal to application roles and organization membership:
        a user with a role, and a user with no application role but an
        organization membership, both authenticate successfully.

        This is a focused authentication-boundary test. It does not
        duplicate the /me shape tests (see tests/test_auth_me.py) or
        the organization-only flow tests (see
        tests/test_auth_organization_only.py)."""
        # (a) User with an application role.
        fc_email = _unique_email("fc")
        created_users.emails.append(fc_email)
        _signup(client, fc_email)  # functional_consultant

        r1 = client.post(
            "/api/auth/login",
            json={"email": fc_email, "password": _CURRENT_PW},
        )
        assert r1.status_code == 200, r1.text
        assert "access_token" in r1.json()

        # (b) Organization-only user with no application role.
        org_email = _unique_email("orgonly")
        created_users.emails.append(org_email)
        _signup(
            client,
            org_email,
            account_type="organization",
            organization_name="Auth Boundary Test Org",
        )

        r2 = client.post(
            "/api/auth/login",
            json={"email": org_email, "password": _CURRENT_PW},
        )
        assert r2.status_code == 200, r2.text
        assert "access_token" in r2.json()

        # Both tokens independently authenticate on a no-permission
        # endpoint. The endpoint requires no application permission, so
        # a 200 confirms authentication and not authorization.
        r = client.get(
            "/api/auth/me",
            headers=_headers(r1.json()["access_token"]),
        )
        assert r.status_code == 200

        r = client.get(
            "/api/auth/me",
            headers=_headers(r2.json()["access_token"]),
        )
        assert r.status_code == 200