"""Shared test infrastructure.

This module is deliberately narrow. It provides:

  * client              - a TestClient whose lifespan runs once per test.
  * auth_headers        - a fresh authenticated functional_consultant
                          user, via the shared helper in tests._auth_helpers.
  * mock_email_provider - opt-in capture of outbound emails.
  * cleanup_registry    - tracks users, organizations, and opportunities
                          created by a test, deleted in FK-safe order at
                          teardown. auth_headers registers its user
                          automatically.
  * unique_email()      - helper returning a fresh unique address.

It deliberately does NOT:

  * override DATABASE_URL (tests use the configured PostgreSQL URL);
  * create or migrate the schema (the database is expected to be at
    the current Alembic head before the suite runs);
  * introduce SQLite compatibility branches;
  * wrap tests in a transaction rollback - the application's services
    commit internally, and the isolation strategy is unique test data
    plus the cleanup_registry teardown, matching the pattern already
    established in tests/test_tenant_boundary.py.

Ordering note for tests that need BOTH an authenticated user and email
capture: declare auth_headers BEFORE mock_email_provider in the test's
argument list. The auth flow installs and then clears its own email
provider; if the capture fixture were set up first, the auth flow's
reset would wipe it out.
"""
from __future__ import annotations

import uuid
from typing import List, Tuple

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.db.base import SessionLocal
from src.db.models import (
    Opportunity,
    Organization,
    SessionRecord,
    User,
)
from src.email import reset_email_provider, set_email_provider
from src.orchestrator_api import app
from tests._auth_helpers import signup_and_authenticate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def unique_email(prefix: str = "test") -> str:
    """Return a fresh unique address. Every test that creates users
    should use this so runs do not collide on the shared PostgreSQL
    database."""
    return f"{prefix}-{uuid.uuid4().hex[:12]}@example.com"


# ---------------------------------------------------------------------------
# Autouse hygiene
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _reset_email_provider_after_test():
    """Reset the email provider to the default after every test.

    Mirrors the pattern already present in tests/test_orchestrator_api.py.
    The auth helper resets its own provider, and mock_email_provider
    resets its own on teardown; this fixture is a belt-and-braces
    guarantee that no test can leave a capturing provider installed
    for the next one.
    """
    yield
    reset_email_provider()


# ---------------------------------------------------------------------------
# Core fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def client():
    """A single TestClient per test, entered as a context manager so
    the FastAPI lifespan runs (and cleanly shuts down) around the
    test body."""
    with TestClient(app) as c:
        yield c


@pytest.fixture
def auth_headers(client, cleanup_registry):
    """A fresh authenticated functional_consultant user, returned as
    Bearer authorization headers.

    Delegates to tests._auth_helpers.signup_and_authenticate, which
    runs the full signup -> verify-email -> login -> verify-otp flow.

    The generated email is registered with cleanup_registry so the
    user is removed in the fixture's teardown.
    """
    email = unique_email("auth")
    cleanup_registry.emails.append(email)
    token = signup_and_authenticate(
        client,
        email=email,
        account_type="functional_consultant",
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def mock_email_provider():
    """Opt-in capturing email provider.

    Yields a list of (to, subject, body) tuples capturing every email
    sent through the application's public email interface during the
    test body. The provider is reset on teardown regardless of test
    outcome.

    Declare AFTER auth_headers in the test signature. The auth flow
    installs and then clears its own provider; if this fixture were
    set up first, the auth flow's reset would wipe out the capture.
    """
    captured: List[Tuple[str, str, str]] = []

    def _capture(to: str, subject: str, body: str) -> None:
        captured.append((to, subject, body))

    set_email_provider(_capture)
    try:
        yield captured
    finally:
        reset_email_provider()


# ---------------------------------------------------------------------------
# Cleanup registry
# ---------------------------------------------------------------------------
class _CleanupRegistry:
    """Tracked identifiers for FK-safe teardown.

    Tests append to these lists as they create rows. Users are tracked
    by email because tests have access to the email before signup
    returns an id."""

    def __init__(self) -> None:
        self.emails: List[str] = []
        self.org_ids: List[str] = []
        self.opportunity_ids: List[str] = []


@pytest.fixture
def cleanup_registry():
    """Removes the users, organizations, and opportunities a test
    creates, in FK-safe order.

    Deletion order:

      1. Sessions belonging to tracked organizations. Required first
         because sessions.organization_id is ON DELETE RESTRICT - the
         organization cannot be deleted while a session still
         references it.
      2. Sessions owned by tracked users. Covers personal projects
         and any session rows left over from tests that did not delete
         org-owned sessions explicitly.
      3. Opportunities tracked by id. Defensive: most cascade-delete
         when their owning organization is removed, but this catches
         rows whose owning org is not in the tracked set.
      4. Organizations tracked by id. Cascades memberships,
         opportunities, firm-knowledge entries, and opportunity child
         documents via the FK declarations on those tables.
      5. Organizations created by tracked users (covers orgs created
         through the real organization signup flow).
      6. Users. Cascades user_roles, remaining memberships, auth-state
         rows, attention items where the user is a recipient, and any
         remaining rows with a user_id FK.

    Bulk deletes are used because the tests in this suite do not
    exercise object storage. A future test that uploads a file would
    need to route its teardown through DbSessionService.delete_session
    so that the object-storage cleanup path runs.
    """
    reg = _CleanupRegistry()
    yield reg

    lowered = [e.lower() for e in reg.emails]

    db: Session = SessionLocal()
    try:
        user_ids: List[str] = []
        if lowered:
            user_rows = db.query(User).filter(User.email.in_(lowered)).all()
            user_ids = [u.id for u in user_rows]

        if reg.org_ids:
            db.query(SessionRecord).filter(
                SessionRecord.organization_id.in_(reg.org_ids)
            ).delete(synchronize_session=False)

        if user_ids:
            db.query(SessionRecord).filter(
                SessionRecord.user_id.in_(user_ids)
            ).delete(synchronize_session=False)

        if reg.opportunity_ids:
            db.query(Opportunity).filter(
                Opportunity.id.in_(reg.opportunity_ids)
            ).delete(synchronize_session=False)

        if reg.org_ids:
            db.query(Organization).filter(
                Organization.id.in_(reg.org_ids)
            ).delete(synchronize_session=False)

        if user_ids:
            db.query(Organization).filter(
                Organization.created_by.in_(user_ids)
            ).delete(synchronize_session=False)

        if user_ids:
            db.query(User).filter(
                User.id.in_(user_ids)
            ).delete(synchronize_session=False)

        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()