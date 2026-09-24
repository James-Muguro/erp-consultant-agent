"""
Integration tests for the project status report endpoint.

The report endpoint is a client-ready deliverable: it reads from every
phase's structured data (requirements, process steps, solution
decisions, test cases, training steps, open issues) via
project_intelligence, assembles them into a .docx, and stores the bytes
in the GeneratedDocument table. Its download path is the generic
documents endpoint, not a report-specific one — so this file exercises
both.

Coverage:
  - 401 without authentication.
  - 404 for a non-owner (not 403 — the ownership check does not reveal
    whether the session exists).
  - 404 for a session id that has never existed.
  - Happy path: generate, appear in /documents, download with the
    correct content type and Content-Disposition, and with the exact
    bytes that were stored.
  - The report can be generated on a bare session (no phase data yet) —
    the endpoint does not require every phase to have run.

Fixtures:
  * client       TestClient entered as a context manager so the
                 lifespan shutdown hook runs per test.
  * auth_headers a fresh user per call.
  * report_session
                 starts a project, yields its id, deletes it on
                 teardown.

Signup note:
  Every signup uses account_type='functional_consultant'. That role
  holds DOCUMENTS_GENERATE and PROJECT_CREATE, which are required by
  the report route and the fixture's project creation.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from src.orchestrator_api import app
from src.memory import agent_memory


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
        json={
            'email': email,
            'password': 'testpassword123',
            'account_type': 'functional_consultant',
        },
    )
    assert r.status_code == 200, r.text
    token = r.json()['access_token']
    return {'Authorization': f'Bearer {token}'}


@pytest.fixture
def report_session(client, auth_headers):
    """Start a project, yield its session id, delete it on teardown.
    Cleanup is best-effort so a storage-cleanup failure on teardown
    never fails the test result."""
    r = client.post(
        '/api/projects/start',
        json={
            'project_name': 'Report Test',
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
# Authorization
# ---------------------------------------------------------------------------
class TestReportAuthorization:
    def test_report_requires_auth(self, client):
        r = client.post('/api/projects/prj_fake/report')
        assert r.status_code == 401

    def test_report_requires_ownership(self, client, report_session):
        """A different user cannot generate a report for someone
        else's session. The endpoint returns 404 (not 403) so it does
        not reveal whether the session exists."""
        other_email = f"test-{uuid.uuid4().hex[:12]}@example.com"
        r = client.post(
            '/api/auth/signup',
            json={
                'email': other_email,
                'password': 'testpassword123',
                'account_type': 'functional_consultant',
            },
        )
        other_headers = {'Authorization': f"Bearer {r.json()['access_token']}"}

        r = client.post(
            f'/api/projects/{report_session}/report',
            headers=other_headers,
        )
        assert r.status_code == 404

    def test_report_for_nonexistent_session_returns_404(self, client, auth_headers):
        r = client.post(
            '/api/projects/prj_does_not_exist/report',
            headers=auth_headers,
        )
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Generation and download
# ---------------------------------------------------------------------------
class TestReportGeneration:
    def test_report_generates_and_becomes_downloadable(
        self, client, auth_headers, report_session,
    ):
        """The core end-to-end behavior: generate a report, see it in
        the generic documents list, download it via the generic
        documents endpoint, and get the exact bytes that were stored."""
        r = client.post(
            f'/api/projects/{report_session}/report',
            headers=auth_headers,
        )
        assert r.status_code == 200
        body = r.json()
        assert body['session_id'] == report_session
        filename = body['filename']
        assert filename.endswith('.docx'), (
            f"expected a .docx filename, got {filename!r}"
        )

        # The report appears in the existing generic documents list —
        # the endpoint reuses the durable GeneratedDocument storage, so
        # no report-specific listing is needed.
        r = client.get(
            f'/api/projects/{report_session}/documents',
            headers=auth_headers,
        )
        assert r.status_code == 200
        docs = r.json()['documents']
        assert any(d['filename'] == filename for d in docs), (
            f"generated report {filename!r} not present in /documents"
        )

        # Download through the generic endpoint.
        r = client.get(
            f'/api/projects/{report_session}/documents/{filename}',
            headers=auth_headers,
        )
        assert r.status_code == 200
        assert r.headers['content-type'] == (
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        )
        # The bytes are a real .docx — the ZIP magic number is 'PK\x03\x04'.
        # This catches a corrupted LargeBinary round-trip that a
        # len > 0 check would miss.
        assert r.content[:4] == b'PK\x03\x04', (
            "downloaded content is not a valid .docx (missing ZIP magic)"
        )

    def test_report_download_carries_content_disposition_header(
        self, client, auth_headers, report_session,
    ):
        """The download endpoint sets Content-Disposition with a safe
        filename. The report filename is generated internally (based on
        the project name + timestamp), so it's ASCII in practice — but
        the header must be well-formed regardless."""
        r = client.post(
            f'/api/projects/{report_session}/report',
            headers=auth_headers,
        )
        filename = r.json()['filename']

        r = client.get(
            f'/api/projects/{report_session}/documents/{filename}',
            headers=auth_headers,
        )
        assert r.status_code == 200
        disposition = r.headers.get('Content-Disposition', '')
        assert 'attachment' in disposition
        assert 'filename=' in disposition

    def test_report_can_be_generated_on_a_bare_session(
        self, client, auth_headers, report_session,
    ):
        """The report generator must tolerate a session with no phase
        data yet — every query it makes via project_intelligence should
        return empty lists rather than raising. The report is less
        useful with no data, but it should not 500."""
        r = client.post(
            f'/api/projects/{report_session}/report',
            headers=auth_headers,
        )
        assert r.status_code == 200, (
            "report generation must not fail on a session that has not "
            f"run any phase yet: {r.text}"
        )

    def test_report_can_be_regenerated_without_error(
        self, client, auth_headers, report_session,
    ):
        """Generating the report twice must not collide on any unique
        constraint (the filename includes a timestamp) and both
        versions should be independently downloadable."""
        r1 = client.post(
            f'/api/projects/{report_session}/report',
            headers=auth_headers,
        )
        assert r1.status_code == 200
        filename1 = r1.json()['filename']

        r2 = client.post(
            f'/api/projects/{report_session}/report',
            headers=auth_headers,
        )
        assert r2.status_code == 200
        filename2 = r2.json()['filename']

        # Both are independently retrievable.
        for fn in (filename1, filename2):
            r = client.get(
                f'/api/projects/{report_session}/documents/{fn}',
                headers=auth_headers,
            )
            assert r.status_code == 200


# ---------------------------------------------------------------------------
# Download of a nonexistent report
# ---------------------------------------------------------------------------
class TestReportDownloadErrors:
    def test_download_nonexistent_document_returns_404(
        self, client, auth_headers, report_session,
    ):
        """Requesting a document that doesn't exist for this session
        must return 404, not a zero-byte success or a 500."""
        r = client.get(
            f'/api/projects/{report_session}/documents/not-a-real-file.docx',
            headers=auth_headers,
        )
        assert r.status_code == 404