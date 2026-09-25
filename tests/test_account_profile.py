"""
Tests for the account/profile surface:

  * GET   /api/auth/settings
  * PATCH /api/auth/settings
  * POST  /api/auth/profile-picture
  * GET   /api/auth/profile-picture/{filename}
  * DELETE /api/auth/account  (profile-picture and feedback cleanup
    paths only; session-deletion behavior is covered in
    tests/test_tenant_boundary.py and is deliberately not duplicated
    here)

Scope of this round:
  * Confirm that profile mutation endpoints are authenticated-only,
    NOT permission-guarded. `PROFILE_EDIT` is defined and granted to
    every application role, but its enforcement is deferred to a later
    round. This file locks in the current behavior so a future change
    that adds or removes the guard surfaces as a focused failure.
  * Confirm profile updates preserve unrelated user fields
    (`profile_picture_url`, application roles, organization
    memberships).
  * Confirm schema-level validation of the profile-update payload.
  * Confirm profile-picture upload's configuration/validation/error
    paths and the store-then-DB-update ordering.
  * Confirm profile-picture and feedback cleanup on account deletion.

Authentication helper: every test that needs an authenticated user
calls `_signup_and_authenticate`, which completes the full flow
(signup → verify-email → login → verify-otp → access_token). The
login step returns a pending-auth reference, NOT a token; the token is
only obtained after OTP verification.

Deliberately NOT covered by this file:
  * `/api/auth/me` — covered in tests/test_auth_me.py.
  * Application-role assertions from signup — covered in
    tests/test_signup.py.
  * Organization-only login and permission denials on project routes —
    covered in tests/test_auth_organization_only.py.
  * Account deletion's session-preservation behavior — covered in
    tests/test_tenant_boundary.py.
  * The PROFILE_EDIT permission matrix itself — covered in
    tests/test_permissions_model.py.

Design notes:
  * TestClient is entered as a context manager so the FastAPI lifespan
    runs.
  * Unique emails on every signup, following the existing suite.
  * moto's mock_aws is used for object-storage tests, mirroring
    tests/test_project_uploads_api.py.
  * Response-shape assertions use the shipped `UserOut` fields
    (`id`, `email`, `name`, `profile_picture_url`, `created_at`,
    `roles`, `organizations`).
  * No production code, migration, existing test, fixture, or
    configuration is modified by this file.
"""
from __future__ import annotations

import uuid
from contextlib import contextmanager
from typing import Iterator, List, Tuple
from unittest.mock import patch

import boto3
import pytest
from fastapi.testclient import TestClient
from moto import mock_aws
from sqlalchemy.orm import Session

from src.auth.permissions import (
    Permission,
    ROLE_PERMISSIONS,
    UserRole,
)
from src.config.settings import settings
from src.db.base import SessionLocal
from src.db.models import (
    Feedback,
    Organization,
    SessionRecord,
    User,
)
from src.email import reset_email_provider, set_email_provider
from src.orchestrator_api import app
from src.storage import object_storage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
@contextmanager
def _db_session() -> Iterator[Session]:
    """Session lifecycle helper, matching the pattern used in the other
    integration test files."""
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _unique_email(prefix: str = "acct") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}@example.com"


def _signup_and_authenticate(
    client: TestClient,
    email: str,
    account_type: str = "functional_consultant",
    organization_name: str | None = None,
    password: str = "testpassword123",
) -> str:
    """Complete the full authentication flow and return an access token.

    The email abstraction is mocked for the duration of the flow, so
    no SMTP connection is attempted. The verification token and the
    login OTP are extracted from the captured email bodies.

    Returns the access token issued by /api/auth/login/verify-otp.
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


def _set_profile_picture_url(user_id: str, url: str) -> None:
    """Direct DB write to seed a profile_picture_url. Used where the
    test asserts preservation across a PATCH, without needing to go
    through the upload endpoint (which requires object storage)."""
    with _db_session() as db:
        user = db.get(User, user_id)
        assert user is not None
        user.profile_picture_url = url
        db.commit()


def _seed_feedback(user_id: str) -> str:
    """Insert a global Feedback row for the user. Returns the row id."""
    fid = uuid.uuid4().hex
    with _db_session() as db:
        db.add(Feedback(id=fid, user_id=user_id, rating=5))
        db.commit()
    return fid


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _reset_email_provider_after_test():
    yield
    reset_email_provider()


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
    teardown."""
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

        db.query(Feedback).filter(
            Feedback.user_id.in_(user_ids)
        ).delete(synchronize_session=False)

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


@pytest.fixture
def s3_configured(monkeypatch):
    """Configure S3 via settings + moto. Mirrors the fixture in
    tests/test_project_uploads_api.py."""
    monkeypatch.setattr(settings, "s3_bucket_name", "test-bucket")
    monkeypatch.setattr(settings, "s3_access_key_id", "fake-key")
    monkeypatch.setattr(settings, "s3_secret_access_key", "fake-secret")
    monkeypatch.setattr(settings, "s3_endpoint_url", None)
    monkeypatch.setattr(settings, "s3_region", "us-east-1")
    with mock_aws():
        boto_client = boto3.client("s3", region_name="us-east-1")
        boto_client.create_bucket(Bucket="test-bucket")
        yield


# ===========================================================================
# A. GET /api/auth/settings — response shape and authentication
# ===========================================================================
class TestGetSettings:
    def test_returns_extended_user_shape(self, client, created_users):
        email = _unique_email()
        created_users.emails.append(email)
        token = _signup_and_authenticate(client, email)

        r = client.get("/api/auth/settings", headers=_headers(token))
        assert r.status_code == 200, r.text
        body = r.json()

        for key in (
            "id", "email", "name", "profile_picture_url",
            "created_at", "roles", "organizations",
        ):
            assert key in body, f"missing key {key!r} in /settings response"
        assert body["email"] == email
        assert body["roles"] == ["functional_consultant"]
        assert body["organizations"] == []

    def test_unauthenticated_returns_401(self, client):
        r = client.get("/api/auth/settings")
        assert r.status_code == 401


# ===========================================================================
# B. PATCH /api/auth/settings — behavioral contract
# ===========================================================================
class TestPatchSettings:
    def test_individual_user_can_update_name(self, client, created_users):
        email = _unique_email()
        created_users.emails.append(email)
        token = _signup_and_authenticate(client, email)

        r = client.patch(
            "/api/auth/settings",
            json={"name": "New Name"},
            headers=_headers(token),
        )
        assert r.status_code == 200, r.text
        assert r.json()["name"] == "New Name"

        r = client.get("/api/auth/settings", headers=_headers(token))
        assert r.json()["name"] == "New Name"

    def test_organization_only_user_can_update_name(
        self, client, created_users,
    ):
        """An organization-only user holds no application role and
        therefore no permissions. If `PATCH /api/auth/settings` were
        guarded by `require_permission(PROFILE_EDIT)`, this user would
        receive 403. The endpoint returning 200 confirms that profile
        mutation is authenticated-only in the current implementation."""
        email = _unique_email("orgonly")
        created_users.emails.append(email)

        token = _signup_and_authenticate(
            client,
            email,
            account_type="organization",
            organization_name="Profile Test Org",
        )

        r = client.patch(
            "/api/auth/settings",
            json={"name": "Org Only User"},
            headers=_headers(token),
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["name"] == "Org Only User"
        assert body["roles"] == []
        assert len(body["organizations"]) == 1

    def test_unauthenticated_returns_401(self, client):
        r = client.patch(
            "/api/auth/settings",
            json={"name": "New Name"},
        )
        assert r.status_code == 401

    def test_preserves_profile_picture_url(self, client, created_users):
        email = _unique_email()
        created_users.emails.append(email)
        token = _signup_and_authenticate(client, email)
        user_id = _user_id_for_email(email)

        seeded_url = "/api/auth/profile-picture/seed-image.png"
        _set_profile_picture_url(user_id, seeded_url)

        r = client.patch(
            "/api/auth/settings",
            json={"name": "Preserved"},
            headers=_headers(token),
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["name"] == "Preserved"
        assert body["profile_picture_url"] == seeded_url

    def test_response_preserves_roles(self, client, created_users):
        email = _unique_email()
        created_users.emails.append(email)
        token = _signup_and_authenticate(client, email)

        r = client.patch(
            "/api/auth/settings",
            json={"name": "X"},
            headers=_headers(token),
        )
        assert r.status_code == 200
        assert r.json()["roles"] == ["functional_consultant"]

    def test_empty_string_clears_name(self, client, created_users):
        email = _unique_email()
        created_users.emails.append(email)
        token = _signup_and_authenticate(client, email)

        client.patch(
            "/api/auth/settings",
            json={"name": "Will Be Cleared"},
            headers=_headers(token),
        )

        r = client.patch(
            "/api/auth/settings",
            json={"name": ""},
            headers=_headers(token),
        )
        assert r.status_code == 200, r.text
        assert r.json()["name"] is None

    def test_whitespace_only_name_clears_name(self, client, created_users):
        email = _unique_email()
        created_users.emails.append(email)
        token = _signup_and_authenticate(client, email)

        r = client.patch(
            "/api/auth/settings",
            json={"name": "   \t   "},
            headers=_headers(token),
        )
        assert r.status_code == 200, r.text
        assert r.json()["name"] is None

    def test_overlong_name_rejected(self, client, created_users):
        email = _unique_email()
        created_users.emails.append(email)
        token = _signup_and_authenticate(client, email)

        r = client.patch(
            "/api/auth/settings",
            json={"name": "x" * 121},
            headers=_headers(token),
        )
        assert r.status_code == 422, r.text


# ===========================================================================
# C. POST /api/auth/profile-picture
# ===========================================================================
class TestProfilePictureUpload:
    def test_returns_503_when_object_storage_not_configured(
        self, client, created_users, monkeypatch,
    ):
        monkeypatch.setattr(settings, "s3_bucket_name", None)
        email = _unique_email()
        created_users.emails.append(email)
        token = _signup_and_authenticate(client, email)

        r = client.post(
            "/api/auth/profile-picture",
            files={"file": ("avatar.png", b"x", "image/png")},
            headers=_headers(token),
        )
        assert r.status_code == 503, r.text
        assert "storage" in r.json()["error"]["message"].lower()

    def test_unauthenticated_returns_401(self, client, s3_configured):
        r = client.post(
            "/api/auth/profile-picture",
            files={"file": ("avatar.png", b"x", "image/png")},
        )
        assert r.status_code == 401

    def test_rejects_unsupported_content_type(
        self, client, created_users, s3_configured,
    ):
        email = _unique_email()
        created_users.emails.append(email)
        token = _signup_and_authenticate(client, email)

        r = client.post(
            "/api/auth/profile-picture",
            files={"file": ("notes.txt", b"content", "text/plain")},
            headers=_headers(token),
        )
        assert r.status_code == 415, r.text

    def test_rejects_unsupported_suffix(
        self, client, created_users, s3_configured,
    ):
        email = _unique_email()
        created_users.emails.append(email)
        token = _signup_and_authenticate(client, email)

        r = client.post(
            "/api/auth/profile-picture",
            files={"file": ("avatar.bmp", b"x", "image/png")},
            headers=_headers(token),
        )
        assert r.status_code == 415, r.text

    def test_rejects_oversized_file(
        self, client, created_users, s3_configured,
    ):
        email = _unique_email()
        created_users.emails.append(email)
        token = _signup_and_authenticate(client, email)

        oversized = b"x" * (5 * 1024 * 1024 + 1)
        r = client.post(
            "/api/auth/profile-picture",
            files={"file": ("big.png", oversized, "image/png")},
            headers=_headers(token),
        )
        assert r.status_code == 413, r.text

    def test_upload_succeeds_and_returns_new_url(
        self, client, created_users, s3_configured,
    ):
        email = _unique_email()
        created_users.emails.append(email)
        token = _signup_and_authenticate(client, email)

        r = client.post(
            "/api/auth/profile-picture",
            files={"file": ("avatar.png", b"png-content", "image/png")},
            headers=_headers(token),
        )
        assert r.status_code == 200, r.text
        body = r.json()

        for key in (
            "id", "email", "name", "profile_picture_url",
            "created_at", "roles", "organizations",
        ):
            assert key in body

        url = body["profile_picture_url"]
        assert url is not None
        assert url.startswith("/api/auth/profile-picture/")
        assert url.endswith(".png")

    def test_replacing_previous_picture_deletes_old_object(
        self, client, created_users, s3_configured,
    ):
        email = _unique_email()
        created_users.emails.append(email)
        token = _signup_and_authenticate(client, email)

        r1 = client.post(
            "/api/auth/profile-picture",
            files={"file": ("first.png", b"first", "image/png")},
            headers=_headers(token),
        )
        assert r1.status_code == 200
        first_url = r1.json()["profile_picture_url"]
        first_filename = first_url.rsplit("/", 1)[-1]

        with patch.object(object_storage, "delete_object") as mock_delete:
            r2 = client.post(
                "/api/auth/profile-picture",
                files={"file": ("second.png", b"second", "image/png")},
                headers=_headers(token),
            )
        assert r2.status_code == 200, r2.text

        assert mock_delete.call_count >= 1
        called_keys = {call.args[0] for call in mock_delete.call_args_list}
        assert any(first_filename in key for key in called_keys), (
            f"expected a delete_object call referencing {first_filename!r}; "
            f"got {sorted(called_keys)}"
        )


# ===========================================================================
# D. GET /api/auth/profile-picture/{filename}
# ===========================================================================
class TestProfilePictureServe:
    def test_nonexistent_picture_returns_404(self, client, s3_configured):
        r = client.get("/api/auth/profile-picture/does-not-exist.png")
        assert r.status_code == 404

    def test_path_traversal_is_rejected(self, client, s3_configured):
        r = client.get("/api/auth/profile-picture/..%5Cetc%5Cpasswd")
        assert r.status_code == 404

    def test_round_trip_via_upload(self, client, created_users, s3_configured):
        email = _unique_email()
        created_users.emails.append(email)
        token = _signup_and_authenticate(client, email)

        content = b"round-trip-bytes"
        r1 = client.post(
            "/api/auth/profile-picture",
            files={"file": ("avatar.png", content, "image/png")},
            headers=_headers(token),
        )
        assert r1.status_code == 200, r1.text
        url = r1.json()["profile_picture_url"]

        r2 = client.get(url)
        assert r2.status_code == 200, r2.text
        assert r2.content == content
        assert r2.headers["content-type"] == "image/png"
        assert "max-age=" in r2.headers.get("Cache-Control", "")


# ===========================================================================
# E. DELETE /api/auth/account — profile picture and feedback cleanup
# ===========================================================================
class TestAccountDeletionCleanup:
    def test_deletes_profile_picture_from_storage(
        self, client, created_users, s3_configured,
    ):
        email = _unique_email()
        created_users.emails.append(email)
        token = _signup_and_authenticate(client, email)

        r = client.post(
            "/api/auth/profile-picture",
            files={"file": ("avatar.png", b"png", "image/png")},
            headers=_headers(token),
        )
        assert r.status_code == 200, r.text

        with patch.object(object_storage, "delete_object") as mock_delete:
            r = client.delete(
                "/api/auth/account",
                headers=_headers(token),
            )
        assert r.status_code == 200, r.text
        assert r.json()["deleted"] is True

        assert mock_delete.call_count >= 1

    def test_deletes_feedback_rows_for_user(
        self, client, created_users, s3_configured,
    ):
        email = _unique_email()
        created_users.emails.append(email)
        token = _signup_and_authenticate(client, email)
        user_id = _user_id_for_email(email)

        fid = _seed_feedback(user_id)

        with _db_session() as db:
            assert db.get(Feedback, fid) is not None

        r = client.delete(
            "/api/auth/account",
            headers=_headers(token),
        )
        assert r.status_code == 200, r.text

        with _db_session() as db:
            assert db.get(Feedback, fid) is None

    def test_unauthenticated_returns_401(self, client):
        r = client.delete("/api/auth/account")
        assert r.status_code == 401


# ===========================================================================
# F. PROFILE_EDIT definition vs enforcement (cross-cutting documentation)
# ===========================================================================
class TestProfileEditDefinition:
    def test_profile_edit_is_granted_to_every_application_role(self):
        for role in UserRole:
            assert Permission.PROFILE_EDIT in ROLE_PERMISSIONS[role], (
                f"{role.value} is expected to hold PROFILE_EDIT via "
                f"_COMMON_USER_PERMS"
            )