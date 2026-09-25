"""
Integration tests for the signup flow.

Coverage:

  Individual signup
    - Each of the four application account types (erp_user,
      functional_consultant, developer, marketer) creates exactly one
      matching UserRoleRecord and no other role rows.

  Organization signup
    - Creates exactly one User, exactly one Organization, exactly one
      OrganizationMembership with role='owner', and zero UserRoleRecord
      rows.
    - organization_name is required.
    - Whitespace-only organization_name is rejected.
    - Duplicate email returns 409.

  Atomicity
    - A failure inside create_organization rolls back the User row and
      any partial Organization row.
    - A failure inside grant_role rolls back the User row and any
      partial UserRoleRecord row.

Design notes:
  * TestClient is entered as a context manager so the FastAPI lifespan
    runs. raise_server_exceptions=False is set so tests that
    deliberately trigger an unhandled exception observe the 500
    response the registered exception handler produces, rather than
    seeing the exception propagate into the test. This mirrors the
    pattern used in tests/test_project_uploads_api.py.

  * The unique-email pattern matches the existing suite (see
    _new_user_headers in tests/test_orchestrator_api.py): each test
    generates a fresh address so parallel runs cannot collide.

  * Row assertions are made on primitive values extracted inside a
    fresh SessionLocal(), not on detached ORM instances. This mirrors
    the DB inspection pattern in tests/test_consistency_check_api.py
    and avoids detached-instance issues after the session closes.

  * The route commits inside create_user, so the data written during
    the request is visible to a fresh SessionLocal() opened from the
    test. No test here inspects data through the running request
    session.

  * No production code, existing test file, fixture, migration, or
    product capability is modified by this file. The tests cover only
    behavior that already exists in the repository.
"""
from __future__ import annotations

import uuid
from contextlib import contextmanager
from typing import Iterator, List, Optional

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from unittest.mock import patch

from src.db.base import SessionLocal
from src.db.models import (
    Organization,
    OrganizationMembership,
    User,
    UserRoleRecord,
)
from src.orchestrator_api import app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
@contextmanager
def _db_session() -> Iterator[Session]:
    """Local session lifecycle helper, matching the pattern used in
    tests/test_consistency_check_api.py. Guarantees the session is
    closed even on exception and rolls back on failure so a partially
    consumed snapshot does not linger."""
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _unique_email() -> str:
    return f"signup-test-{uuid.uuid4().hex[:12]}@example.com"


def _user_id_for_email(email: str) -> Optional[str]:
    with _db_session() as db:
        return (
            db.query(User.id)
            .filter(User.email == email.lower())
            .scalar()
        )


def _roles_for_user(user_id: str) -> List[str]:
    """Return the list of application role strings granted to this user,
    ordered as returned by the DB (no ORDER BY is used, matching the
    simple query style in the rest of the suite)."""
    with _db_session() as db:
        return [
            row[0]
            for row in db.query(UserRoleRecord.role)
            .filter(UserRoleRecord.user_id == user_id)
            .all()
        ]


def _orgs_for_owner(user_id: str) -> List[tuple]:
    """Return (organization_id, name) tuples for organizations created
    by this user (Organization.created_by)."""
    with _db_session() as db:
        return [
            (o.id, o.name)
            for o in db.query(Organization)
            .filter(Organization.created_by == user_id)
            .all()
        ]


def _memberships_for_user(user_id: str) -> List[tuple]:
    """Return (organization_id, role) tuples for this user's
    organization memberships."""
    with _db_session() as db:
        return [
            (row[0], row[1])
            for row in db.query(
                OrganizationMembership.organization_id,
                OrganizationMembership.role,
            )
            .filter(OrganizationMembership.user_id == user_id)
            .all()
        ]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def client():
    """TestClient entered as a context manager so the lifespan runs.

    raise_server_exceptions=False is set so tests that trigger an
    unhandled exception (see TestAtomicRollback) can inspect the 500
    response produced by the registered exception handler rather than
    having the exception propagate into the test body. This matches the
    TestClient(app, raise_server_exceptions=False) usage in
    tests/test_project_uploads_api.py.
    """
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def created_users():
    """Track the emails created during a test and clean up their rows
    on teardown. Deletion order respects the FK relationships:

      1. Organizations created by these users are deleted; their
         organization_memberships rows cascade via
         organization_memberships.organization_id ON DELETE CASCADE.

      2. The users themselves are deleted; their user_roles rows and
         any remaining organization_memberships rows cascade via the
         ON DELETE CASCADE on user_roles.user_id and
         organization_memberships.user_id respectively.

    Cleanup is a no-op if the test rolled back its own inserts (the
    User row will not exist), so this fixture is safe against both
    success and failure paths.
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

        # Delete orgs created by these users; memberships cascade.
        db.query(Organization).filter(
            Organization.created_by.in_(user_ids)
        ).delete(synchronize_session=False)

        # Delete the users; user_roles and any remaining memberships
        # cascade via the FK ON DELETE CASCADE clauses.
        db.query(User).filter(
            User.id.in_(user_ids)
        ).delete(synchronize_session=False)

        db.commit()


# ---------------------------------------------------------------------------
# Individual signup — each account type creates exactly one role
# ---------------------------------------------------------------------------
class TestIndividualSignup:
    @pytest.mark.parametrize(
        "account_type,expected_role",
        [
            ("erp_user", "erp_user"),
            ("functional_consultant", "functional_consultant"),
            ("developer", "developer"),
            ("marketer", "marketer"),
        ],
    )
    def test_creates_exactly_one_matching_role_record(
        self, client, created_users, account_type, expected_role,
    ):
        email = _unique_email()
        created_users.append(email)

        r = client.post(
            "/api/auth/signup",
            json={
                "email": email,
                "password": "testpassword123",
                "account_type": account_type,
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        # Signup issues no tokens; the response is the enumeration-
        # resistant MessageResponse. Role assignment is verified below
        # directly against the DB, which is what this test actually
        # checks.
        assert "message" in body
        assert "access_token" not in body
        assert "token_type" not in body
        assert "refresh_token" not in body

        user_id = _user_id_for_email(email)
        assert user_id is not None

        # Exactly one UserRoleRecord, matching the chosen account type.
        assert _roles_for_user(user_id) == [expected_role]

        # No organization side effects for individual signup.
        assert _orgs_for_owner(user_id) == []
        assert _memberships_for_user(user_id) == []


# ---------------------------------------------------------------------------
# Organization signup
# ---------------------------------------------------------------------------
class TestOrganizationSignup:
    def test_creates_one_user_one_org_one_owner_membership_zero_roles(
        self, client, created_users,
    ):
        """Organization signup is a tenant creation flow. It creates
        the User, the Organization, and one OrganizationMembership
        with role='owner', and it does NOT create any UserRoleRecord:
        Organization is a tenant context, not an application role."""
        email = _unique_email()
        created_users.append(email)
        org_name = f"Test Org {uuid.uuid4().hex[:6]}"

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
        body = r.json()
        # Post-migration: signup returns a generic message and does not
        # issue tokens. A token is only obtained after verify-email + OTP.
        assert "access_token" not in body
        assert "message" in body

        user_id = _user_id_for_email(email)
        assert user_id is not None

        # Zero application roles: Organization is not an application
        # role and must not be persisted as a UserRoleRecord.
        assert _roles_for_user(user_id) == []

        # Exactly one Organization, with the supplied name, created by
        # this user.
        orgs = _orgs_for_owner(user_id)
        assert len(orgs) == 1
        org_id, stored_name = orgs[0]
        assert stored_name == org_name

        # Exactly one membership, role='owner', for the just-created
        # organization.
        memberships = _memberships_for_user(user_id)
        assert len(memberships) == 1
        assert memberships[0] == (org_id, "owner")

    def test_organization_name_is_required(self, client, created_users):
        """Omitting organization_name on an organization signup is
        rejected by the schema validator (422). No User row is
        created."""
        email = _unique_email()
        created_users.append(email)

        r = client.post(
            "/api/auth/signup",
            json={
                "email": email,
                "password": "testpassword123",
                "account_type": "organization",
                # organization_name intentionally omitted
            },
        )
        assert r.status_code == 422, r.text

        # No partial state was created.
        assert _user_id_for_email(email) is None

    def test_whitespace_only_organization_name_is_rejected(
        self, client, created_users,
    ):
        """A whitespace-only organization_name is stripped to an empty
        string by the field validator and then rejected by the
        model-level validator with 422. No User row is created."""
        email = _unique_email()
        created_users.append(email)

        r = client.post(
            "/api/auth/signup",
            json={
                "email": email,
                "password": "testpassword123",
                "account_type": "organization",
                "organization_name": "   \t  ",
            },
        )
        assert r.status_code == 422, r.text

        assert _user_id_for_email(email) is None


# ---------------------------------------------------------------------------
# Duplicate email
# ---------------------------------------------------------------------------
class TestDuplicateEmail:
    def test_duplicate_email_returns_generic_success(
        self, client, created_users,
    ):
        """Duplicate signup is enumeration-resistant: the response is
        identical to a fresh signup (200 + generic message), NOT 409.
        A 409 would reveal account existence."""
        email = _unique_email()
        created_users.append(email)

        payload = {
            "email": email,
            "password": "testpassword123",
            "account_type": "functional_consultant",
        }
        r1 = client.post("/api/auth/signup", json=payload)
        r2 = client.post("/api/auth/signup", json=payload)

        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r1.json() == r2.json()


# ---------------------------------------------------------------------------
# Atomic rollback
# ---------------------------------------------------------------------------
def _create_org_then_fail(db, name, owner_user_id):
    """Simulate a partial failure inside create_organization: add the
    Organization row and flush (so its INSERT hits the DB within the
    current transaction), then raise. The surrounding transaction in
    create_user must roll the whole thing back — including the User
    row that was also pending.

    db.flush() is used rather than db.commit() so the INSERTs go to
    the database but remain inside the open transaction; the rollback
    issued by create_user's except block will then undo them.
    """
    org = Organization(
        id=uuid.uuid4().hex,
        name=name,
        created_by=owner_user_id,
    )
    db.add(org)
    db.flush()
    raise RuntimeError("simulated failure after partial org insert")


def _grant_role_then_fail(db, user_id, role):
    """Simulate a partial failure inside grant_role: add the
    UserRoleRecord row and flush, then raise. The surrounding
    transaction in create_user must roll the whole thing back."""
    row = UserRoleRecord(
        id=uuid.uuid4().hex,
        user_id=user_id,
        role=role.value,
    )
    db.add(row)
    db.flush()
    raise RuntimeError("simulated failure after partial role insert")


class TestAtomicRollback:
    def test_signup_organization_rolls_back_when_create_organization_fails(
        self, client, created_users,
    ):
        """If create_organization raises after a partial insert, the
        whole signup transaction rolls back: no User, no Organization,
        no OrganizationMembership."""
        email = _unique_email()
        created_users.append(email)
        sentinel_name = "Will Not Persist"

        with patch(
            "src.auth.service.create_organization",
            side_effect=_create_org_then_fail,
        ):
            r = client.post(
                "/api/auth/signup",
                json={
                    "email": email,
                    "password": "testpassword123",
                    "account_type": "organization",
                    "organization_name": sentinel_name,
                },
            )
        assert r.status_code == 500, r.text

        # The User row was rolled back.
        assert _user_id_for_email(email) is None

        # The partial Organization row was rolled back with it.
        with _db_session() as db:
            leftover_orgs = (
                db.query(Organization)
                .filter(Organization.name == sentinel_name)
                .all()
            )
        assert leftover_orgs == []

    def test_signup_individual_rolls_back_when_grant_role_fails(
        self, client, created_users,
    ):
        """If grant_role raises after a partial insert on an individual
        signup, the whole transaction rolls back: no User and no
        UserRoleRecord. Asserting on the absence of the User is
        sufficient — a surviving UserRoleRecord would require the User
        to exist by FK constraint."""
        email = _unique_email()
        created_users.append(email)

        with patch(
            "src.auth.service.grant_role",
            side_effect=_grant_role_then_fail,
        ):
            r = client.post(
                "/api/auth/signup",
                json={
                    "email": email,
                    "password": "testpassword123",
                    "account_type": "developer",
                },
            )
        assert r.status_code == 500, r.text

        assert _user_id_for_email(email) is None