"""
Integration tests for the consistency-check endpoint.

The endpoint runs the deterministic cross-document consistency checks
(src/services/consistency_checker.py — no LLM calls) and records any
findings as ProjectIssue rows. Its two contracts:

  1. It returns the findings it just produced, with the count and the
     findings themselves in the response body.
  2. Findings are recorded as open ProjectIssue rows the caller can
     retrieve via GET /issues.

Both are exercised below.

Coverage:
  - 401 without authentication.
  - 404 for a non-owner (not 403 — the ownership check does not
    reveal whether the session exists).
  - Happy path: a session containing a decision that recommends a
    different ERP than the configured one produces at least one
    finding, and that finding is retrievable as a ProjectIssue.
  - A clean session produces zero findings and no new issues — the
    checker must not fabricate contradictions.
  - The response shape includes `findings_count`, `findings`, and
    `session_id`.

Fixtures:
  * client       TestClient entered as a context manager so the
                 lifespan shutdown hook runs per test.
  * auth_headers a fresh user per call.
  * cc_session   starts a project, yields its id, deletes it on
                 teardown.

Implementation note on DB seeding:
  The contradiction case needs a SolutionDecision row that the checker
  can flag. Rather than going through the sync layer (which would
  also populate trace links and additional fields this test does not
  care about), the row is inserted directly with a helper that owns
  its session lifecycle. Direct insertion is deliberately scoped to a
  small helper so the session leak risk is contained.
"""
from __future__ import annotations

import uuid
from contextlib import contextmanager
from typing import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.db.base import SessionLocal
from src.db.models import SolutionDecision
from src.memory import agent_memory
from src.orchestrator_api import app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def client():
    """TestClient whose lifespan runs for the test and shuts down
    cleanly at the end (releasing the resilience thread pool)."""
    with TestClient(app) as c:
        yield c


@pytest.fixture
def auth_headers(client):
    """Sign up a fresh, unique user and return Authorization headers."""
    email = f"test-{uuid.uuid4().hex[:12]}@example.com"
    r = client.post(
        '/api/auth/signup',
        json={'email': email, 'password': 'testpassword123'},
    )
    assert r.status_code == 200, r.text
    token = r.json()['access_token']
    return {'Authorization': f'Bearer {token}'}


@pytest.fixture
def cc_session(client, auth_headers):
    """Start a project configured for SAP S/4HANA, yield its id, delete
    it on teardown."""
    r = client.post(
        '/api/projects/start',
        json={
            'project_name': 'CC Test',
            'module': 'FI',
            'erp_system': 'SAP S/4HANA',
        },
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    session_id = r.json()['session_id']
    try:
        yield session_id
    finally:
        try:
            agent_memory.session_service.delete_session(session_id)
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# DB helper
# ---------------------------------------------------------------------------
@contextmanager
def _db_session() -> Iterator[Session]:
    """Local session lifecycle helper for test seeding. Guarantees the
    session is closed even on exception, and rolls back on failure so a
    partially-committed seeding doesn't leak into the next assertion."""
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _seed_conflicting_erp_decision(session_id: str) -> str:
    """Insert a SolutionDecision that recommends Oracle for a session
    configured for SAP. Returns the decision id (unused by callers, but
    useful for debugging when a test fails)."""
    decision_id = uuid.uuid4().hex
    with _db_session() as db:
        db.add(SolutionDecision(
            id=decision_id,
            session_id=session_id,
            decision_type='erp_selection',
            component='core',
            lineage_id=uuid.uuid4().hex,
            description='Recommend Oracle Fusion for this deployment',
        ))
        db.commit()
    return decision_id


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------
class TestConsistencyCheckAuthorization:
    def test_requires_auth(self, client):
        r = client.post('/api/projects/prj_fake/consistency-check')
        assert r.status_code == 401

    def test_requires_ownership(self, client, cc_session):
        """A different user cannot run the check on someone else's
        session. 404 (not 403) so the endpoint does not reveal whether
        the session exists."""
        other_email = f"test-{uuid.uuid4().hex[:12]}@example.com"
        r = client.post(
            '/api/auth/signup',
            json={'email': other_email, 'password': 'testpassword123'},
        )
        other_headers = {'Authorization': f"Bearer {r.json()['access_token']}"}

        r = client.post(
            f'/api/projects/{cc_session}/consistency-check',
            headers=other_headers,
        )
        assert r.status_code == 404

    def test_nonexistent_session_returns_404(self, client, auth_headers):
        r = client.post(
            '/api/projects/prj_does_not_exist/consistency-check',
            headers=auth_headers,
        )
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Response shape
# ---------------------------------------------------------------------------
class TestConsistencyCheckResponseShape:
    def test_response_has_expected_keys(self, client, auth_headers, cc_session):
        """The response always carries session_id, findings_count, and
        findings — even when findings is empty. The SPA relies on the
        keys being present, not on conditional access."""
        r = client.post(
            f'/api/projects/{cc_session}/consistency-check',
            headers=auth_headers,
        )
        assert r.status_code == 200
        body = r.json()
        assert body['session_id'] == cc_session
        assert 'findings_count' in body
        assert 'findings' in body
        assert isinstance(body['findings'], list)
        assert body['findings_count'] == len(body['findings'])


# ---------------------------------------------------------------------------
# Contradiction detection
# ---------------------------------------------------------------------------
class TestContradictionDetection:
    def test_finds_erp_conflict_and_records_it_as_an_issue(
        self, client, auth_headers, cc_session,
    ):
        """A session configured for SAP S/4HANA that contains a
        decision recommending Oracle Fusion is a direct contradiction.
        The checker must find it and record it as an open ProjectIssue."""
        _seed_conflicting_erp_decision(cc_session)

        r = client.post(
            f'/api/projects/{cc_session}/consistency-check',
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        body = r.json()

        # Assert the finding itself, not just the count. The count
        # could theoretically be affected by other rules the checker
        # grows over time; the substance is "an Oracle-related conflict
        # was found".
        assert body['findings_count'] >= 1, (
            f"expected at least one finding for a SAP-configured session "
            f"with an Oracle decision; got {body['findings_count']}"
        )
        assert any(
            'oracle' in str(f).lower() for f in body['findings']
        ), f"no finding mentions Oracle: {body['findings']}"

        # And the finding is retrievable as an issue. Assert on the
        # issues endpoint specifically, since a caller relying on the
        # SPA's issue view depends on this path.
        r = client.get(
            f'/api/projects/{cc_session}/issues?status=open',
            headers=auth_headers,
        )
        assert r.status_code == 200
        issues = r.json()['issues']
        assert any('oracle' in i['description'].lower() for i in issues), (
            f"the Oracle finding was not recorded as an issue: {issues}"
        )

    def test_clean_session_produces_no_findings(
        self, client, auth_headers, cc_session,
    ):
        """The counterpart to the conflict case: a session with no
        contradictions must return zero findings and record no new
        issues. A checker that flagged everything would pass the
        conflict test but fail this one."""
        r = client.post(
            f'/api/projects/{cc_session}/consistency-check',
            headers=auth_headers,
        )
        assert r.status_code == 200
        body = r.json()
        assert body['findings_count'] == 0, (
            f"a fresh session with no phase data should produce no "
            f"findings; got {body['findings']}"
        )
        assert body['findings'] == []

        # No open consistency-check issues were recorded.
        r = client.get(
            f'/api/projects/{cc_session}/issues?status=open',
            headers=auth_headers,
        )
        assert r.status_code == 200
        # We can't assert `issues == []` in general (other endpoints
        # could theoretically have recorded some), but there should be
        # nothing that names the consistency checker as its source.
        # If the checker records a specific issue_type, tighten this.
        assert not any(
            'oracle' in i['description'].lower() for i in r.json()['issues']
        )

    def test_rerunning_the_check_does_not_duplicate_issues(
        self, client, auth_headers, cc_session,
    ):
        """Running the check twice on the same session must not produce
        two issues for the same underlying contradiction — the issue
        list would become unusable if every click of the "Run check"
        button filed another copy."""
        _seed_conflicting_erp_decision(cc_session)

        r = client.post(
            f'/api/projects/{cc_session}/consistency-check',
            headers=auth_headers,
        )
        assert r.status_code == 200

        r = client.get(
            f'/api/projects/{cc_session}/issues?status=open',
            headers=auth_headers,
        )
        count_after_first = sum(
            1 for i in r.json()['issues']
            if 'oracle' in i['description'].lower()
        )

        # Run again.
        client.post(
            f'/api/projects/{cc_session}/consistency-check',
            headers=auth_headers,
        )
        r = client.get(
            f'/api/projects/{cc_session}/issues?status=open',
            headers=auth_headers,
        )
        count_after_second = sum(
            1 for i in r.json()['issues']
            if 'oracle' in i['description'].lower()
        )

        # The improved checker uses create_issue with dedupe semantics
        # for some issue types; if this assertion fails, it means
        # duplicate-filing protection needs to be added for this rule.
        assert count_after_second == count_after_first, (
            "running the consistency check twice produced duplicate "
            f"issues ({count_after_first} → {count_after_second})"
        )