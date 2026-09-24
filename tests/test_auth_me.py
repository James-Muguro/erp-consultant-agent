"""
Integration tests for GET /api/auth/me.

Coverage:

  Individual signup
    - /me returns roles as a single-element list containing the
      application role granted at signup, and organizations as an
      empty list.

  Organization signup
    - /me returns roles as an empty list (Organization is a tenant
      context, not an application role), and organizations as a
      single-element list containing one entry with role='owner'.

  Both axes
    - A user with an application role AND an organization membership
      receives both axes correctly: roles contains the application
      role, organizations contains the organization membership with
      the organization role. The two axes are independent — neither
      derives from the other.

  Response shape
    - Both keys (roles, organizations) are always present in the
      response, even when empty. The frontend reads them directly and
      does not guard against missing keys, so their presence is part
      of the contract.

Design notes:
  * TestClient is entered as a context manager so the FastAPI lifespan
    runs.

  * To construct a user with both axes, the test signs up via the real
    /api/auth/signup endpoint (for the application role) and then
    inserts the Organization and OrganizationMembership rows directly
    via SQLAlchemy. There is no endpoint in the current repository for
    granting an application role to an existing user or for adding a
    membership to an existing user, so direct insertion is the only way
    to construct the fixture. This mirrors the direct-DB seeding
    pattern used in tests/test_consistency_check_api.py (see
    _seed_conflicting_erp_decision).

  * Cleanup follows the pattern in tests/test_signup.py: delete
    organizations created by the tracked users (their memberships
    cascade via organization_memberships.organization_id ON DELETE
    CASCADE), then delete the users (their user_roles and any
    remaining memberships cascade via the same FK clauses on user_id).

  * No production code, existing test file, fixture, migration, or
    product capability is modified by this file.
"""
from __future__ import annotations

import uuid
from contextlib import contextmanager
from typing import Iterator, List, Optional, Tuple

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.db.base import SessionLocal
from src.db.models import (
    Organization,
    OrganizationMembership,
    User,
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
    return f"auth-me-test-{uuid.uuid4().hex[:12]}@example.com"


def _user_id_for_email(email: str) -> Optional[str]:
    with _db_session() as db:
        return (
            db.query(User.id)
            .filter(User.email == email.lower())
            .scalar()
        )


def _seed_owner_membership(user_id: str, org_name: str) -> Tuple[str, str]:
    """Insert an Organization and an OrganizationMembership for the
    given user, both committed. Returns (organization_id, org_name).

    Used to construct a user with both axes when the user was created
    via the individual signup flow. There is no endpoint in the
    repository for adding a membership to an existing user, so direct
    insertion is the only available mechanism. Mirrors the direct-DB
    seeding pattern in tests/test_consistency_check_api.py.
    """
    org_id = uuid.uuid4().hex
    with _db_session() as db:
        db.add(Organization(
            id=org_id,
            name=org_name,
            created_by=user_id,
        ))
        db.add(OrganizationMembership(
            id=uuid.uuid4().hex,
            organization_id=org_id,
            user_id=user_id,
            role="owner",
        ))
        db.commit()
    return org_id, org_name


def _signup_individual(
    client: TestClient,
    email: str,
    account_type: str,
) -> str:
    """Sign up an individual account and return the access token."""
    r = client.post(
        "/api/auth/signup",
        json={
            "email": email,
            "password": "testpassword123",
            "account_type": account_type,
        },
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _signup_organization(
    client: TestClient,
    email: str,
    org_name: str,
) -> str:
    """Sign up an organization account and return the access token."""
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
    return r.json()["access_token"]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def client():
    """TestClient entered as a context manager so the lifespan runs."""
    with TestClient(app) as c:
        yield c


@pytest.fixture
def created_users():
    """Track emails created during a test and clean up their rows on
    teardown.

    Deletion order:
      1. Organizations created by these users (their memberships
         cascade via organization_memberships.organization_id ON
         DELETE CASCADE).
      2. The users themselves (user_roles and any remaining
         organization_memberships cascade via their user_id FKs).

    A no-op when the test created no users.
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

        db.query(Organization).filter(
            Organization.created_by.in_(user_ids)
        ).delete(synchronize_session=False)

        db.query(User).filter(
            User.id.in_(user_ids)
        ).delete(synchronize_session=False)

        db.commit()


# ---------------------------------------------------------------------------
# Individual signup
# ---------------------------------------------------------------------------
class TestIndividualSignupMe:
    @pytest.mark.parametrize(
        "account_type",
        ["erp_user", "functional_consultant", "developer", "marketer"],
    )
    def test_me_returns_matching_role_and_empty_organizations(
        self, client, created_users, account_type,
    ):
        """An individual signup produces a user with exactly one
        application role and no organization memberships. /me must
        reflect both."""
        email = _unique_email()
        created_users.append(email)

        token = _signup_individual(client, email, account_type)
        headers = {"Authorization": f"Bearer {token}"}

        r = client.get("/api/auth/me", headers=headers)
        assert r.status_code == 200, r.text
        body = r.json()

        assert body["email"] == email
        assert body["roles"] == [account_type]
        assert body["organizations"] == []


# ---------------------------------------------------------------------------
# Organization signup
# ---------------------------------------------------------------------------
class TestOrganizationSignupMe:
    def test_me_returns_empty_roles_and_one_owner_organization(
        self, client, created_users,
    ):
        """Organization signup produces a user with zero application
        roles and exactly one organization membership with
        role='owner'. /me must reflect both — the two axes are
        independent."""
        email = _unique_email()
        created_users.append(email)
        org_name = f"Me Test Org {uuid.uuid4().hex[:6]}"

        token = _signup_organization(client, email, org_name)
        headers = {"Authorization": f"Bearer {token}"}

        r = client.get("/api/auth/me", headers=headers)
        assert r.status_code == 200, r.text
        body = r.json()

        assert body["email"] == email
        # Organization is a tenant context, not an application role.
        assert body["roles"] == []
        # Exactly one organization membership, role='owner'.
        assert len(body["organizations"]) == 1
        org_entry = body["organizations"][0]
        assert org_entry["name"] == org_name
        assert org_entry["role"] == "owner"
        # The id is a non-empty string; its exact value is not asserted
        # here because it is generated server-side and is not part of
        # the test's input contract.
        assert isinstance(org_entry["id"], str) and org_entry["id"]


# ---------------------------------------------------------------------------
# Both axes
# ---------------------------------------------------------------------------
class TestBothAxes:
    def test_me_returns_application_role_and_organization_membership(
        self, client, created_users,
    ):
        """A user who holds an application role AND belongs to an
        organization receives both axes correctly. The organization
        axis does not appear in roles, and the application axis does
        not appear in organizations — they remain separate."""
        email = _unique_email()
        created_users.append(email)

        # Real signup grants the application role.
        token = _signup_individual(client, email, "developer")

        user_id = _user_id_for_email(email)
        assert user_id is not None

        # No endpoint exists for adding a membership to an existing
        # user, so the org and membership are inserted directly. See
        # module docstring.
        org_name = f"Both Axes Org {uuid.uuid4().hex[:6]}"
        org_id, _ = _seed_owner_membership(user_id, org_name)

        headers = {"Authorization": f"Bearer {token}"}
        r = client.get("/api/auth/me", headers=headers)
        assert r.status_code == 200, r.text
        body = r.json()

        assert body["roles"] == ["developer"]

        assert len(body["organizations"]) == 1
        org_entry = body["organizations"][0]
        assert org_entry["id"] == org_id
        assert org_entry["name"] == org_name
        assert org_entry["role"] == "owner"


# ---------------------------------------------------------------------------
# Response shape
# ---------------------------------------------------------------------------
class TestMeResponseShape:
    def test_me_always_includes_roles_and_organizations_keys(
        self, client, created_users,
    ):
        """Both keys are present in the response even when their values
        are empty. The frontend reads them directly and does not guard
        against missing keys, so their presence is part of the
        contract."""
        email = _unique_email()
        created_users.append(email)

        # Individual signup — roles is non-empty, organizations empty.
        token = _signup_individual(client, email, "erp_user")
        headers = {"Authorization": f"Bearer {token}"}

        r = client.get("/api/auth/me", headers=headers)
        assert r.status_code == 200
        body = r.json()
        assert "roles" in body
        assert "organizations" in body
        assert isinstance(body["roles"], list)
        assert isinstance(body["organizations"], list)

    def test_me_org_only_user_still_includes_both_keys(
        self, client, created_users,
    ):
        """The empty-roles case is the one most likely to be affected
        by an over-eager serializer that drops empty fields. Assert the
        key exists explicitly when roles is empty."""
        email = _unique_email()
        created_users.append(email)
        org_name = f"Shape Org {uuid.uuid4().hex[:6]}"

        token = _signup_organization(client, email, org_name)
        headers = {"Authorization": f"Bearer {token}"}

        r = client.get("/api/auth/me", headers=headers)
        assert r.status_code == 200
        body = r.json()
        assert "roles" in body
        assert "organizations" in body
        assert body["roles"] == []
        assert isinstance(body["organizations"], list)
        assert len(body["organizations"]) == 1