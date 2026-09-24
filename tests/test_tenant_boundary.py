"""
Integration tests for the organization tenant boundary introduced in
Rounds 2 and 3a.

Scope of this file:
  * Personal projects are accessible only to their owner, using the
    original `session.user_id == current_user.id` rule.
  * Organization-owned projects are accessible only to active members
    of the owning organization, using an `OrganizationMembership` row.
  * Non-members receive 404 for organization-owned project access.
  * `list_project_summaries_for_user` includes organization-owned
    projects for members, and excludes them for non-members.
  * `list_sessions_for_user` returns only personal sessions.
  * Account deletion removes personal sessions but preserves
    organization-owned sessions and clears their `user_id`
    attribution via the `ON DELETE SET NULL` FK.

This file deliberately does NOT test the application permission
matrix. Every caller in this file holds the application permission
required to reach the tenant check (via the `functional_consultant`
account type, which is granted `PROJECT_CREATE`, `PROJECT_READ`, etc.).
Permission-denial behavior is tested separately in
`tests/test_permissions_routes.py`.

Design notes:

  * TestClient is entered as a context manager so the FastAPI lifespan
    runs.

  * Users are created through the real `/api/auth/signup` endpoint with
    explicit `account_type` values, matching the pattern established in
    `tests/test_signup.py` and `tests/test_auth_me.py`.

  * Organizations and memberships are inserted directly via SQLAlchemy
    when the test needs a specific org the caller did not create through
    signup. There is no endpoint for adding a membership to an existing
    user, so direct insertion is the only available mechanism. This
    mirrors the direct-DB seeding pattern used in
    `tests/test_consistency_check_api.py` (see
    `_seed_conflicting_erp_decision`).

  * Cleanup is handled by a single `cleanup_registry` fixture that
    tracks both user emails and explicitly-created organization ids.
    Teardown deletes rows in this order to satisfy FK constraints:

      1. Sessions referencing tracked organizations. Required because
         `sessions.organization_id` declares `ON DELETE RESTRICT`, so
         an organization cannot be deleted while any session still
         references it.
      2. Sessions owned by tracked users. Covers personal sessions and
         any leftover rows after account deletion.
      3. Organizations by explicit id. Cascades their memberships via
         `organization_memberships.organization_id ON DELETE CASCADE`.
      4. Organizations still reachable via `created_by IN user_ids`.
         Covers orgs created through the real organization signup flow
         (which sets `created_by` to the new user).
      5. Users. Cascades `user_roles` and any remaining
         `organization_memberships` rows via their `user_id` FKs.

    Bulk deletes are used for the session rows because the tests do not
    create uploaded documents, so the object-storage cleanup path in
    `DbSessionService.delete_session` has nothing to do. This is noted
    only for a future test that uploads a file — that test would need
    to route its teardown through the service method instead.

  * No production code, migration, existing test file, fixture, or
    configuration is modified by this file.
"""
from __future__ import annotations

import uuid
from contextlib import contextmanager
from typing import Iterator, List, Optional

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.auth.permissions import OrganizationRole
from src.db.base import SessionLocal
from src.db.models import (
    Organization,
    OrganizationMembership,
    SessionRecord,
    User,
    UserRoleRecord,
)
from src.memory import agent_memory
from src.orchestrator_api import app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
@contextmanager
def _db_session() -> Iterator[Session]:
    """Local session lifecycle helper, matching the pattern used in
    tests/test_consistency_check_api.py."""
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _unique_email() -> str:
    return f"tenant-test-{uuid.uuid4().hex[:12]}@example.com"


def _unique_name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _signup_individual(
    client: TestClient,
    email: str,
    account_type: str = "functional_consultant",
) -> str:
    """Sign up an individual account and return the access token.

    Defaults to `functional_consultant`, whose permission set includes
    PROJECT_CREATE, PROJECT_READ, PROJECT_EDIT, and PROJECT_DELETE, so
    callers reach the tenant-boundary check on every project-scoped
    route exercised in this file."""
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


def _user_id_for_email(email: str) -> Optional[str]:
    with _db_session() as db:
        return (
            db.query(User.id)
            .filter(User.email == email.lower())
            .scalar()
        )


def _insert_org_with_owner(owner_user_id: str, org_name: str) -> str:
    """Insert an Organization and its owner OrganizationMembership in
    one transaction. Returns the organization id.

    Used when a test needs an organization that was not created through
    the real organization signup endpoint, so the caller can already
    hold an application role (e.g. `functional_consultant`) and reach
    the project-scoped routes this file exercises."""
    org_id = uuid.uuid4().hex
    with _db_session() as db:
        db.add(Organization(
            id=org_id,
            name=org_name,
            created_by=owner_user_id,
        ))
        db.add(OrganizationMembership(
            id=uuid.uuid4().hex,
            organization_id=org_id,
            user_id=owner_user_id,
            role=OrganizationRole.OWNER.value,
        ))
        db.commit()
    return org_id


def _insert_membership(user_id: str, org_id: str, role: str) -> str:
    """Insert a single OrganizationMembership row. Returns the row id.

    Role is one of OrganizationRole.<X>.value strings ("owner",
    "admin", "member")."""
    membership_id = uuid.uuid4().hex
    with _db_session() as db:
        db.add(OrganizationMembership(
            id=membership_id,
            organization_id=org_id,
            user_id=user_id,
            role=role,
        ))
        db.commit()
    return membership_id


def _create_project(
    client: TestClient,
    headers: dict,
    project_name: str,
    organization_id: Optional[str] = None,
) -> str:
    """POST /api/projects/start and return the created session id."""
    payload = {"project_name": project_name, "module": "FI"}
    if organization_id is not None:
        payload["organization_id"] = organization_id
    r = client.post("/api/projects/start", json=payload, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["session_id"]


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def client():
    """TestClient entered as a context manager so the lifespan runs."""
    with TestClient(app) as c:
        yield c


class _CleanupRegistry:
    """Simple container for cleanup state: emails of users created by a
    test, and ids of organizations inserted directly. Teardown reads
    these to delete the rows created during the test."""

    def __init__(self):
        self.emails: List[str] = []
        self.org_ids: List[str] = []


@pytest.fixture
def cleanup_registry():
    reg = _CleanupRegistry()
    yield reg

    lowered = [e.lower() for e in reg.emails]

    with _db_session() as db:
        user_rows = (
            db.query(User).filter(User.email.in_(lowered)).all()
            if lowered else []
        )
        user_ids = [u.id for u in user_rows]

        # 1. Sessions referencing tracked organizations. Required
        # because sessions.organization_id is ON DELETE RESTRICT.
        if reg.org_ids:
            db.query(SessionRecord).filter(
                SessionRecord.organization_id.in_(reg.org_ids)
            ).delete(synchronize_session=False)

        # 2. Sessions owned by tracked users (personal sessions and any
        # remaining rows after a partial test teardown).
        if user_ids:
            db.query(SessionRecord).filter(
                SessionRecord.user_id.in_(user_ids)
            ).delete(synchronize_session=False)

        # 3. Organizations by explicit id. Cascades their memberships.
        if reg.org_ids:
            db.query(Organization).filter(
                Organization.id.in_(reg.org_ids)
            ).delete(synchronize_session=False)

        # 4. Any remaining organizations created by tracked users
        # (e.g. created through the real organization signup flow).
        if user_ids:
            db.query(Organization).filter(
                Organization.created_by.in_(user_ids)
            ).delete(synchronize_session=False)

        # 5. Users themselves. Cascades user_roles and any remaining
        # memberships via the user_id FKs.
        if user_ids:
            db.query(User).filter(
                User.id.in_(user_ids)
            ).delete(synchronize_session=False)

        db.commit()


# ---------------------------------------------------------------------------
# 1. Personal project access — unchanged
# ---------------------------------------------------------------------------
class TestPersonalProjectAccess:
    def test_personal_project_owner_access_unchanged(
        self, client, cleanup_registry,
    ):
        """A user can access their own personal project (organization_id
        IS NULL) under the original `session.user_id == current_user.id`
        rule."""
        owner_email = _unique_email()
        cleanup_registry.emails.append(owner_email)
        owner_token = _signup_individual(client, owner_email)

        sid = _create_project(
            client, _auth_headers(owner_token), "Personal Project",
        )

        r = client.get(
            f"/api/projects/{sid}/status",
            headers=_auth_headers(owner_token),
        )
        assert r.status_code == 200, r.text
        assert r.json()["session_id"] == sid

    def test_personal_project_other_user_receives_404(
        self, client, cleanup_registry,
    ):
        """A different authenticated user receives 404 for another
        user's personal project. 404, not 403, preserves the
        non-disclosure property of `_get_owned_session`."""
        owner_email = _unique_email()
        other_email = _unique_email()
        cleanup_registry.emails.extend([owner_email, other_email])
        owner_token = _signup_individual(client, owner_email)
        other_token = _signup_individual(client, other_email)

        sid = _create_project(
            client, _auth_headers(owner_token), "Personal Project",
        )

        r = client.get(
            f"/api/projects/{sid}/status",
            headers=_auth_headers(other_token),
        )
        assert r.status_code == 404, r.text
        body = r.json()
        assert body["error"]["code"] == 404


# ---------------------------------------------------------------------------
# 2. Organization-owned project access by members
# ---------------------------------------------------------------------------
class TestOrganizationProjectAccess:
    def test_organization_member_can_access_org_project(
        self, client, cleanup_registry,
    ):
        """A non-creator member of the owning organization can access
        an organization-owned project. The `session.user_id` field is
        attribution only; access is determined by the membership row."""
        owner_email = _unique_email()
        member_email = _unique_email()
        cleanup_registry.emails.extend([owner_email, member_email])
        owner_token = _signup_individual(client, owner_email)
        member_token = _signup_individual(client, member_email)

        owner_id = _user_id_for_email(owner_email)
        member_id = _user_id_for_email(member_email)
        assert owner_id is not None and member_id is not None

        org_id = _insert_org_with_owner(owner_id, _unique_name("org"))
        cleanup_registry.org_ids.append(org_id)
        _insert_membership(member_id, org_id, OrganizationRole.MEMBER.value)

        sid = _create_project(
            client,
            _auth_headers(owner_token),
            "Org Project",
            organization_id=org_id,
        )

        # The member (not the creator) can access the org-owned project.
        r = client.get(
            f"/api/projects/{sid}/status",
            headers=_auth_headers(member_token),
        )
        assert r.status_code == 200, r.text
        assert r.json()["session_id"] == sid

    def test_non_member_receives_404_for_org_project(
        self, client, cleanup_registry,
    ):
        """A user who is not a member of the owning organization
        receives 404 for the organization-owned project, even though
        they hold PROJECT_READ (via functional_consultant). The tenant
        check runs before any data is returned."""
        owner_email = _unique_email()
        outsider_email = _unique_email()
        cleanup_registry.emails.extend([owner_email, outsider_email])
        owner_token = _signup_individual(client, owner_email)
        outsider_token = _signup_individual(client, outsider_email)

        owner_id = _user_id_for_email(owner_email)
        assert owner_id is not None

        org_id = _insert_org_with_owner(owner_id, _unique_name("org"))
        cleanup_registry.org_ids.append(org_id)

        sid = _create_project(
            client,
            _auth_headers(owner_token),
            "Org Project",
            organization_id=org_id,
        )

        r = client.get(
            f"/api/projects/{sid}/status",
            headers=_auth_headers(outsider_token),
        )
        assert r.status_code == 404, r.text
        body = r.json()
        assert body["error"]["code"] == 404


# ---------------------------------------------------------------------------
# 3. Organization-owned project creation — non-member rejection
# ---------------------------------------------------------------------------
class TestOrganizationProjectStart:
    def test_org_project_start_rejects_non_member_with_404(
        self, client, cleanup_registry,
    ):
        """POST /api/projects/start with an organization_id the caller
        is not a member of returns 404. The caller holds PROJECT_CREATE
        (functional_consultant), so the rejection is caused by the
        tenant check, not by permission denial."""
        owner_email = _unique_email()
        outsider_email = _unique_email()
        cleanup_registry.emails.extend([owner_email, outsider_email])
        owner_token = _signup_individual(client, owner_email)
        outsider_token = _signup_individual(client, outsider_email)

        owner_id = _user_id_for_email(owner_email)
        assert owner_id is not None

        org_id = _insert_org_with_owner(owner_id, _unique_name("org"))
        cleanup_registry.org_ids.append(org_id)

        r = client.post(
            "/api/projects/start",
            json={
                "project_name": "Should Not Be Created",
                "module": "FI",
                "organization_id": org_id,
            },
            headers=_auth_headers(outsider_token),
        )
        assert r.status_code == 404, r.text
        assert r.json()["error"]["code"] == 404

    def test_org_project_start_requires_organization_membership(
        self, client, cleanup_registry,
    ):
        """Reinforces the previous test by asserting that no session
        row was created for the rejected caller: the tenant check runs
        before any persistence side effect. Query by the outsider's
        user_id; a fresh user should have zero sessions."""
        owner_email = _unique_email()
        outsider_email = _unique_email()
        cleanup_registry.emails.extend([owner_email, outsider_email])
        _signup_individual(client, owner_email)
        outsider_token = _signup_individual(client, outsider_email)

        owner_id = _user_id_for_email(owner_email)
        outsider_id = _user_id_for_email(outsider_email)
        assert owner_id is not None and outsider_id is not None

        org_id = _insert_org_with_owner(owner_id, _unique_name("org"))
        cleanup_registry.org_ids.append(org_id)

        r = client.post(
            "/api/projects/start",
            json={
                "project_name": "Rejected Project",
                "module": "FI",
                "organization_id": org_id,
            },
            headers=_auth_headers(outsider_token),
        )
        assert r.status_code == 404, r.text

        # No session was created for the outsider.
        with _db_session() as db:
            count = (
                db.query(SessionRecord)
                .filter(SessionRecord.user_id == outsider_id)
                .count()
            )
        assert count == 0


# ---------------------------------------------------------------------------
# 4. Project listing — tenant-aware visibility
# ---------------------------------------------------------------------------
class TestProjectListingVisibility:
    def test_project_list_includes_org_projects_for_members(
        self, client, cleanup_registry,
    ):
        """A member of the owning organization sees the organization's
        projects in GET /api/projects, without having to know the
        session id in advance."""
        owner_email = _unique_email()
        member_email = _unique_email()
        cleanup_registry.emails.extend([owner_email, member_email])
        owner_token = _signup_individual(client, owner_email)
        member_token = _signup_individual(client, member_email)

        owner_id = _user_id_for_email(owner_email)
        member_id = _user_id_for_email(member_email)
        assert owner_id is not None and member_id is not None

        org_id = _insert_org_with_owner(owner_id, _unique_name("org"))
        cleanup_registry.org_ids.append(org_id)
        _insert_membership(member_id, org_id, OrganizationRole.MEMBER.value)

        sid = _create_project(
            client,
            _auth_headers(owner_token),
            "Org Project",
            organization_id=org_id,
        )

        r = client.get(
            "/api/projects",
            headers=_auth_headers(member_token),
        )
        assert r.status_code == 200, r.text
        ids = {p["session_id"] for p in r.json()["projects"]}
        assert sid in ids

    def test_project_list_excludes_org_projects_for_non_members(
        self, client, cleanup_registry,
    ):
        """A user who is not a member of the owning organization does
        not see the organization's projects in GET /api/projects."""
        owner_email = _unique_email()
        outsider_email = _unique_email()
        cleanup_registry.emails.extend([owner_email, outsider_email])
        owner_token = _signup_individual(client, owner_email)
        outsider_token = _signup_individual(client, outsider_email)

        owner_id = _user_id_for_email(owner_email)
        assert owner_id is not None

        org_id = _insert_org_with_owner(owner_id, _unique_name("org"))
        cleanup_registry.org_ids.append(org_id)

        sid = _create_project(
            client,
            _auth_headers(owner_token),
            "Org Project",
            organization_id=org_id,
        )

        r = client.get(
            "/api/projects",
            headers=_auth_headers(outsider_token),
        )
        assert r.status_code == 200, r.text
        ids = {p["session_id"] for p in r.json()["projects"]}
        assert sid not in ids


# ---------------------------------------------------------------------------
# 5. list_sessions_for_user semantics
# ---------------------------------------------------------------------------
class TestListSessionsForUser:
    def test_list_sessions_for_user_returns_only_personal(
        self, client, cleanup_registry,
    ):
        """`list_sessions_for_user` returns only the user's personal
        sessions. Organization-owned sessions are excluded, even when
        the user is a member of the owning organization and even when
        the user created the organization-owned project.

        This is the semantic narrowing introduced in Round 3a to keep
        account deletion from destroying organization-owned project
        data."""
        email = _unique_email()
        cleanup_registry.emails.append(email)
        token = _signup_individual(client, email)

        user_id = _user_id_for_email(email)
        assert user_id is not None

        org_id = _insert_org_with_owner(user_id, _unique_name("org"))
        cleanup_registry.org_ids.append(org_id)

        personal_sid = _create_project(
            client, _auth_headers(token), "Personal Project",
        )
        org_sid = _create_project(
            client,
            _auth_headers(token),
            "Org Project",
            organization_id=org_id,
        )
        assert personal_sid != org_sid

        session_ids = agent_memory.session_service.list_sessions_for_user(
            user_id, include_archived=True,
        )
        assert personal_sid in session_ids
        assert org_sid not in session_ids


# ---------------------------------------------------------------------------
# 6. Account deletion — org-owned sessions survive
# ---------------------------------------------------------------------------
class TestAccountDeletion:
    def test_account_deletion_does_not_delete_org_projects(
        self, client, cleanup_registry,
    ):
        """Deleting a user's account removes their personal sessions
        but preserves organization-owned sessions. The organization
        keeps its projects; only the creator's attribution is cleared
        (via `ON DELETE SET NULL` on `sessions.user_id`)."""
        email = _unique_email()
        cleanup_registry.emails.append(email)
        token = _signup_individual(client, email)

        user_id = _user_id_for_email(email)
        assert user_id is not None

        org_id = _insert_org_with_owner(user_id, _unique_name("org"))
        cleanup_registry.org_ids.append(org_id)

        personal_sid = _create_project(
            client, _auth_headers(token), "Personal Project",
        )
        org_sid = _create_project(
            client,
            _auth_headers(token),
            "Org Project",
            organization_id=org_id,
        )

        # Sanity check: both rows exist and are attributed to the user
        # before deletion.
        with _db_session() as db:
            pre_personal = db.get(SessionRecord, personal_sid)
            pre_org = db.get(SessionRecord, org_sid)
        assert pre_personal is not None and pre_personal.user_id == user_id
        assert pre_org is not None and pre_org.user_id == user_id
        assert pre_org.organization_id == org_id

        r = client.delete(
            "/api/auth/account",
            headers=_auth_headers(token),
        )
        assert r.status_code == 200, r.text
        assert r.json().get("deleted") is True

        with _db_session() as db:
            post_personal = db.get(SessionRecord, personal_sid)
            post_org = db.get(SessionRecord, org_sid)

        # Personal session was deleted.
        assert post_personal is None

        # Organization-owned session survived.
        assert post_org is not None
        # The org id was not cleared.
        assert post_org.organization_id == org_id
        # The user_id attribution was cleared by the FK's ON DELETE
        # SET NULL behavior.
        assert post_org.user_id is None


# ---------------------------------------------------------------------------
# 7. Organization creator's authority lives on the membership
# ---------------------------------------------------------------------------
class TestOrganizationCreatorMembership:
    def test_organization_creator_is_owner_membership_not_user_role(
        self, client, cleanup_registry,
    ):
        """An organization creator's authority comes from
        `OrganizationMembership(role='owner')`, not from any
        `UserRoleRecord`. The organization signup path creates exactly
        one membership and zero application roles for that user.

        Focused on the tenant-model data shape. Broader signup
        semantics (row counts, HTTP responses, /me shape) are covered in
        tests/test_signup.py and tests/test_auth_me.py."""
        email = _unique_email()
        cleanup_registry.emails.append(email)
        org_name = _unique_name("creator-org")

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

        user_id = _user_id_for_email(email)
        assert user_id is not None

        with _db_session() as db:
            memberships = (
                db.query(OrganizationMembership)
                .filter(OrganizationMembership.user_id == user_id)
                .all()
            )
            org = (
                db.query(Organization)
                .filter(Organization.created_by == user_id)
                .one()
            )
            user_roles = (
                db.query(UserRoleRecord)
                .filter(UserRoleRecord.user_id == user_id)
                .all()
            )

        # Authority over the organization is expressed by a single
        # membership row with role='owner'.
        assert len(memberships) == 1
        assert memberships[0].organization_id == org.id
        assert memberships[0].role == OrganizationRole.OWNER.value

        # No application role row exists for this user.
        assert user_roles == []