"""
Integration tests for the orchestrator API.

Coverage:
  Auth lifecycle (signup, login, /me, invalid tokens)
  Project CRUD (start, list, rename, archive, permanent delete)
  Per-user isolation (one user's session invisible to another)
  Health and readiness probes
  Error envelope shape and X-Request-ID correlation
  Chat and streaming chat (SSE)
  Phase execution with parameters (added in the API review)
  Request body size limit (added in the API review)

Fixtures:
  * client      a single TestClient per test, entered via context
                manager so the lifespan runs once and cleanly shuts
                down at the end.
  * auth_headers
                creates a fresh user and returns Bearer headers.
                Each call = one bcrypt signup (~250ms); tests that
                need two distinct users call it twice.

Notes on test behavior:
  * bcrypt at the default cost factor means a signup costs ~250ms.
    Tests that create two users therefore take ~500ms longer than
    single-user tests. If this becomes a problem, an
    environment-variable-driven lower cost for tests would help — but
    that's a Settings change, not a test change.
  * The `mock_info_retriever` in the chat tests returns
    `web_results` as a list of dicts, matching the pre-review
    info_retriever output shape. The real retriever now returns
    strings, but since the mock is patched at the boundary the shape
    doesn't matter for these tests — the endpoint passes whatever it
    receives straight to the synthesis prompt builder, which
    stringifies dict entries.
"""
from __future__ import annotations

import json
import uuid

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch

from src.config.settings import settings
from src.orchestrator_api import app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def client():
    """A TestClient whose lifespan runs for the duration of the test
    and shuts down cleanly at the end. Using the context manager form
    ensures the shutdown hook runs (releasing the resilience thread
    pool, etc.), which the direct `TestClient(app)` form did not."""
    with TestClient(app) as c:
        yield c


def _new_user_headers(client: TestClient) -> dict:
    """Sign up a fresh, unique user and return Authorization headers.
    Every call creates a distinct account, so tests never see each
    other's projects and parallel runs can't collide."""
    email = f"test-{uuid.uuid4().hex[:12]}@example.com"
    r = client.post(
        '/api/auth/signup',
        json={'email': email, 'password': 'testpassword123'},
    )
    assert r.status_code == 200, r.text
    token = r.json()['access_token']
    return {'Authorization': f'Bearer {token}'}


@pytest.fixture
def auth_headers(client):
    """Convenience for single-user tests."""
    return _new_user_headers(client)


# ---------------------------------------------------------------------------
# Health and readiness
# ---------------------------------------------------------------------------
def test_health(client):
    r = client.get('/health')
    assert r.status_code == 200
    assert r.json()['status'] == 'ok'


def test_readiness_check(client):
    r = client.get('/ready')
    assert r.status_code == 200
    assert r.json()['status'] == 'ready'


# ---------------------------------------------------------------------------
# Security headers
# ---------------------------------------------------------------------------
class TestSecurityHeaders:
    """The unconditional headers are on every response. HSTS is
    HTTPS-conditional — see the API review for why. Setting HSTS on a
    plain-HTTP response is ignored by browsers and muddles log
    analysis, so the API only adds it when the request arrived over
    HTTPS (either directly or via a trusted X-Forwarded-Proto)."""

    def test_unconditional_security_headers_present_on_every_response(self, client):
        """Checked against an unauthenticated 401 — these headers are
        unconditional, not something only successful responses get."""
        r = client.get('/api/auth/me')
        assert r.headers.get('X-Content-Type-Options') == 'nosniff'
        assert r.headers.get('X-Frame-Options') == 'DENY'
        assert r.headers.get('Referrer-Policy') == 'strict-origin-when-cross-origin'
        assert 'geolocation=()' in r.headers.get('Permissions-Policy', '')

    def test_hsts_is_absent_on_plain_http(self, client):
        """TestClient sends requests as http://testserver. HSTS must
        not be set on a response served over plain HTTP — browsers
        ignore it and a stray value in a dev environment is misleading."""
        r = client.get('/health')
        assert 'Strict-Transport-Security' not in r.headers

    def test_hsts_is_present_when_forwarded_proto_is_https(self, client):
        """Behind a reverse proxy (Render, Cloudflare, nginx), the
        original scheme arrives as X-Forwarded-Proto. When that header
        says https, the response must carry HSTS."""
        r = client.get(
            '/health',
            headers={'X-Forwarded-Proto': 'https'},
        )
        assert 'max-age=' in r.headers.get('Strict-Transport-Security', '')

    def test_hsts_present_on_unauthenticated_response_over_https(self, client):
        """Security headers apply even to error responses, over HTTPS
        the same as plain HTTP."""
        r = client.get(
            '/api/auth/me',
            headers={'X-Forwarded-Proto': 'https'},
        )
        assert r.status_code == 401
        assert 'max-age=' in r.headers.get('Strict-Transport-Security', '')


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def test_signup_login_me(client):
    email = f"test-{uuid.uuid4().hex[:12]}@example.com"

    r = client.post('/api/auth/signup', json={'email': email, 'password': 'testpassword123'})
    assert r.status_code == 200
    token = r.json()['access_token']

    # Duplicate signup is rejected
    r = client.post('/api/auth/signup', json={'email': email, 'password': 'testpassword123'})
    assert r.status_code == 409

    # Login with correct credentials
    r = client.post('/api/auth/login', json={'email': email, 'password': 'testpassword123'})
    assert r.status_code == 200
    login_token = r.json()['access_token']

    # Login with wrong password is rejected
    r = client.post('/api/auth/login', json={'email': email, 'password': 'wrongpassword'})
    assert r.status_code == 401

    # /me works with a valid token
    r = client.get('/api/auth/me', headers={'Authorization': f'Bearer {login_token}'})
    assert r.status_code == 200
    assert r.json()['email'] == email

    # /me rejects a missing token
    r = client.get('/api/auth/me')
    assert r.status_code == 401

    # /me rejects an invalid token
    r = client.get('/api/auth/me', headers={'Authorization': 'Bearer not-a-real-token'})
    assert r.status_code == 401


def test_signup_rejects_short_password(client):
    """The schema requires at least 12 characters. A one-character
    password is rejected with 422 (schema-level), not 200."""
    email = f"test-{uuid.uuid4().hex[:12]}@example.com"
    r = client.post('/api/auth/signup', json={'email': email, 'password': 'a'})
    assert r.status_code == 422


def test_signup_rejects_common_password(client):
    """A known-weak password is rejected by the schema validator.
    'password1234' is long enough (12 chars) but is on the blocklist."""
    email = f"test-{uuid.uuid4().hex[:12]}@example.com"
    r = client.post('/api/auth/signup', json={'email': email, 'password': 'password1234'})
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------
def test_start_project_minimal(client, auth_headers):
    payload = {'project_name': 'Test Project', 'module': 'FI'}
    r = client.post('/api/projects/start', json=payload, headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert data.get('success') is True
    assert 'session_id' in data
    # The response should include a next_action for the SPA to render.
    assert 'next_action' in data


def test_start_project_requires_auth(client):
    payload = {'project_name': 'Test Project', 'module': 'FI'}
    r = client.post('/api/projects/start', json=payload)
    assert r.status_code == 401


def test_project_isolated_between_users(client):
    """One user's session must be invisible (404, not 403) to another user."""
    headers_a = _new_user_headers(client)
    headers_b = _new_user_headers(client)

    r = client.post(
        '/api/projects/start',
        json={'project_name': 'Owned by A', 'module': 'FI'},
        headers=headers_a,
    )
    session_id = r.json()['session_id']

    # Owner can read their own session
    r = client.get(f'/api/projects/{session_id}/status', headers=headers_a)
    assert r.status_code == 200

    # A different user gets 404, not the project's data
    r = client.get(f'/api/projects/{session_id}/status', headers=headers_b)
    assert r.status_code == 404


def test_list_projects_scoped_to_user(client):
    headers_a = _new_user_headers(client)
    headers_b = _new_user_headers(client)

    client.post('/api/projects/start',
                json={'project_name': 'A Project 1', 'module': 'FI'}, headers=headers_a)
    client.post('/api/projects/start',
                json={'project_name': 'A Project 2', 'module': 'MM'}, headers=headers_a)
    client.post('/api/projects/start',
                json={'project_name': 'B Project 1', 'module': 'SD'}, headers=headers_b)

    r = client.get('/api/projects', headers=headers_a)
    assert r.status_code == 200
    names = {p['project_name'] for p in r.json()['projects']}
    assert names == {'A Project 1', 'A Project 2'}


def test_rename_project(client, auth_headers):
    r = client.post(
        '/api/projects/start',
        json={'project_name': 'Old Name', 'module': 'FI'},
        headers=auth_headers,
    )
    session_id = r.json()['session_id']

    r = client.patch(
        f'/api/projects/{session_id}',
        json={'project_name': 'New Name'},
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert r.json()['project_name'] == 'New Name'

    r = client.get(f'/api/projects/{session_id}/status', headers=auth_headers)
    assert r.json()['project_name'] == 'New Name'


def test_rename_project_requires_ownership(client):
    headers_a = _new_user_headers(client)
    headers_b = _new_user_headers(client)
    r = client.post(
        '/api/projects/start',
        json={'project_name': 'A Project', 'module': 'FI'},
        headers=headers_a,
    )
    session_id = r.json()['session_id']

    r = client.patch(
        f'/api/projects/{session_id}',
        json={'project_name': 'Hijacked'},
        headers=headers_b,
    )
    assert r.status_code == 404


def test_archive_project_hides_from_default_list(client, auth_headers):
    r = client.post(
        '/api/projects/start',
        json={'project_name': 'To Archive', 'module': 'FI'},
        headers=auth_headers,
    )
    session_id = r.json()['session_id']

    r = client.delete(f'/api/projects/{session_id}', headers=auth_headers)
    assert r.status_code == 200
    assert r.json()['archived'] is True

    # Archiving again is a conflict, not silently OK.
    r = client.delete(f'/api/projects/{session_id}', headers=auth_headers)
    assert r.status_code == 409

    # Hidden from the default list...
    r = client.get('/api/projects', headers=auth_headers)
    ids = {p['session_id'] for p in r.json()['projects']}
    assert session_id not in ids

    # ...but still visible with include_archived, and still readable directly.
    r = client.get('/api/projects?include_archived=true', headers=auth_headers)
    ids = {p['session_id'] for p in r.json()['projects']}
    assert session_id in ids

    r = client.get(f'/api/projects/{session_id}/status', headers=auth_headers)
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# Feedback
# ---------------------------------------------------------------------------
def test_feedback_submission(client, auth_headers):
    r = client.post(
        '/api/projects/start',
        json={'project_name': 'Feedback Project', 'module': 'FI'},
        headers=auth_headers,
    )
    session_id = r.json()['session_id']

    r = client.post(
        '/api/feedback',
        json={'session_id': session_id, 'rating': 5, 'comment': 'Great!'},
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert r.json()['success'] is True

    # Invalid rating is rejected (schema-level ge/le validation -> 422).
    r = client.post(
        '/api/feedback',
        json={'session_id': session_id, 'rating': 7},
        headers=auth_headers,
    )
    assert r.status_code == 422

    # Feedback on someone else's session is rejected (404, not 403).
    other_headers = _new_user_headers(client)
    r = client.post(
        '/api/feedback',
        json={'session_id': session_id, 'rating': 3},
        headers=other_headers,
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Error envelope and correlation
# ---------------------------------------------------------------------------
def test_error_envelope_shape(client):
    """Every HTTPException should come back as
    {"error": {code, message, request_id}} and echo the ID in a header."""
    r = client.get('/api/auth/me')
    assert r.status_code == 401
    body = r.json()
    assert 'error' in body
    assert body['error']['code'] == 401
    assert 'message' in body['error']
    assert 'request_id' in body['error']
    # The same ID should also be echoed on the response header.
    assert r.headers.get('X-Request-ID') == body['error']['request_id']


def test_request_id_is_honored_from_header(client):
    """A caller-supplied X-Request-ID is used instead of generating a
    fresh one — required for correlating across services."""
    r = client.get('/api/auth/me', headers={'X-Request-ID': 'caller-supplied-id'})
    assert r.headers.get('X-Request-ID') == 'caller-supplied-id'
    assert r.json()['error']['request_id'] == 'caller-supplied-id'


# ---------------------------------------------------------------------------
# Phase execution with parameters (API-review behavior)
# ---------------------------------------------------------------------------
class TestPhaseExecutionWithBody:
    """The `execute_phase` endpoint now accepts a PhaseExecuteRequest
    body, so phases that need parameters (notably the requirements
    phase, which needs stakeholder_input) can be run through it. The
    original endpoint had no body and could not run the requirements
    phase at all."""

    def _create_session(self, client, headers) -> str:
        r = client.post(
            '/api/projects/start',
            json={'project_name': 'Phase Body Test', 'module': 'FI'},
            headers=headers,
        )
        return r.json()['session_id']

    def test_requirements_phase_accepts_stakeholder_input(self, client, auth_headers):
        session_id = self._create_session(client, auth_headers)

        with patch.dict(
            'src.orchestrator_api._PHASE_EXECUTORS',
            {'requirements': MagicMock(return_value={
                'success': True,
                'document_path': '/tmp/x.docx',
            })},
        ):
            r = client.post(
                f'/api/projects/{session_id}/phase/requirements/execute',
                json={'stakeholder_input': 'We need AP automation.'},
                headers=auth_headers,
            )
        assert r.status_code == 200
        assert r.json()['success'] is True

    def test_requirements_phase_without_input_returns_422(self, client, auth_headers):
        """Missing required phase parameters produce a specific 422,
        not a generic 500 from an internal call with a None argument."""
        session_id = self._create_session(client, auth_headers)
        r = client.post(
            f'/api/projects/{session_id}/phase/requirements/execute',
            json={},
            headers=auth_headers,
        )
        assert r.status_code == 422
        assert 'stakeholder_input' in r.json()['error']['message']

    def test_unknown_phase_returns_400(self, client, auth_headers):
        session_id = self._create_session(client, auth_headers)
        r = client.post(
            f'/api/projects/{session_id}/phase/not_a_phase/execute',
            json={},
            headers=auth_headers,
        )
        assert r.status_code == 400

    def test_phase_requires_ownership(self, client):
        headers_a = _new_user_headers(client)
        headers_b = _new_user_headers(client)
        session_id = self._create_session(client, headers_a)
        r = client.post(
            f'/api/projects/{session_id}/phase/qa_testing/execute',
            json={},
            headers=headers_b,
        )
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Request body size limit (API-review behavior)
# ---------------------------------------------------------------------------
def test_oversized_request_body_is_rejected(client, auth_headers):
    """The body-size middleware rejects requests whose Content-Length
    exceeds the configured limit. Patches max_request_body_mb down so
    the test sends a small payload rather than a multi-MB one."""
    # 0.001 MB ~= 1 KB. Any JSON over ~1 KB is rejected.
    with patch.object(settings, 'max_request_body_mb', 0.001):
        r = client.post(
            '/api/chat',
            json={'message': 'x' * 5_000},
            headers=auth_headers,
        )
    assert r.status_code == 413


# ---------------------------------------------------------------------------
# SSE parser helper
# ---------------------------------------------------------------------------
def _parse_sse(raw_text: str):
    """Parse raw SSE text into a list of (event_type, data_dict) tuples.

    Lines that begin with ':' are SSE comments — the streaming endpoint
    emits `: keepalive` before potentially long operations to keep
    intermediaries from closing an idle connection. Comments are
    ignored by this parser, matching how real SSE clients treat them."""
    events = []
    for block in raw_text.strip().split('\n\n'):
        if not block.strip():
            continue
        event_type = None
        data = None
        for line in block.splitlines():
            if line.startswith('event:'):
                event_type = line[len('event:'):].strip()
            elif line.startswith('data:'):
                data = json.loads(line[len('data:'):].strip())
        if event_type:
            events.append((event_type, data))
    return events


def test_sse_parser_ignores_keepalive_comments():
    """The parser used by the streaming tests must tolerate the
    `: keepalive` comments the endpoint emits. Without this, comment
    blocks would be treated as malformed events."""
    raw = ": keepalive\n\nevent: message_start\ndata: {}\n\n"
    events = _parse_sse(raw)
    assert events == [("message_start", {})]


# ---------------------------------------------------------------------------
# Chat and streaming chat
# ---------------------------------------------------------------------------
def test_chat_stream_requires_auth(client):
    r = client.post('/api/chat/stream', json={'message': 'hello'})
    assert r.status_code == 401


def test_chat_stream_rejects_other_users_session(client):
    headers_a = _new_user_headers(client)
    headers_b = _new_user_headers(client)
    r = client.post(
        '/api/projects/start',
        json={'project_name': 'Streaming Owner Test', 'module': 'FI'},
        headers=headers_a,
    )
    session_id = r.json()['session_id']

    r = client.post(
        '/api/chat/stream',
        json={'message': 'hi', 'session_id': session_id},
        headers=headers_b,
    )
    assert r.status_code == 404


@patch('src.orchestrator_api.info_retriever')
@patch('src.utils.llm.get_llm')
def test_chat_stream_ask_question_events(mock_get_llm, mock_info_retriever, client, auth_headers):
    """Verify the SSE event sequence for a plain question. The
    web_results mock is a list of dicts matching the pre-review
    retriever output — the synthesis prompt builder stringifies whatever
    it receives, so the shape doesn't matter for this test."""
    mock_info_retriever.return_value = {
        'decision': {'decision': 'web', 'confidence': 0.9, 'reasoning': 'Query is a question.'},
        'kb_results': [],
        'web_results': [{'title': 'Test Result', 'snippet': 'A snippet.'}],
    }

    mock_llm = MagicMock()
    mock_llm.generate_content.return_value.text = "Streamed synthesized answer."
    # No generate_content_stream attribute on this mock -> exercises the
    # non-streaming-provider fallback path (single text_delta chunk).
    del mock_llm.generate_content_stream
    mock_get_llm.return_value = mock_llm

    with client.stream(
        'POST',
        '/api/chat/stream',
        json={'message': 'What is a bill of lading?'},
        headers=auth_headers,
    ) as r:
        assert r.status_code == 200
        assert 'text/event-stream' in r.headers['content-type']
        raw = ''.join(r.iter_text())

    events = _parse_sse(raw)
    event_types = [e[0] for e in events]

    assert event_types[0] == 'message_start'
    assert 'agent_started' in event_types
    assert 'tool_started' in event_types
    assert 'tool_completed' in event_types
    assert 'text_delta' in event_types
    assert event_types[-2] == 'workflow_completed'
    assert event_types[-1] == 'message_complete'

    final = events[-1][1]
    assert final['answer'] == "Streamed synthesized answer."

    text_deltas = [d['text'] for t, d in events if t == 'text_delta']
    assert ''.join(text_deltas) == "Streamed synthesized answer."


@patch('src.utils.llm.get_llm')
def test_chat_stream_start_project_events(mock_get_llm, client, auth_headers):
    mock_llm = MagicMock()
    mock_llm.generate_content.return_value.text = json.dumps({
        "intent": "start_project",
        "project_name": "Streamed Project",
        "module": "MM",
    })
    mock_get_llm.return_value = mock_llm

    with client.stream(
        'POST',
        '/api/chat/stream',
        json={'message': "start a new project called Streamed Project for MM"},
        headers=auth_headers,
    ) as r:
        assert r.status_code == 200
        raw = ''.join(r.iter_text())

    events = _parse_sse(raw)
    event_types = [e[0] for e in events]
    assert 'message_start' in event_types
    assert 'workflow_completed' in event_types
    assert event_types[-1] == 'message_complete'
    final = events[-1][1]
    assert final['session_id'] is not None


@patch('src.orchestrator_api.info_retriever')
@patch('src.utils.llm.get_llm')
def test_chat_end_to_end(mock_get_llm, mock_info_retriever, client, auth_headers):
    """Ensure /api/chat returns a synthesized answer, not raw data."""
    mock_info_retriever.return_value = {
        'decision': {'decision': 'web', 'confidence': 0.9, 'reasoning': 'Query is a question.'},
        'kb_results': [],
        'web_results': [{'title': 'Test Result', 'snippet': 'This is a test snippet from the web.'}],
    }

    mock_llm = MagicMock()
    mock_llm.generate_content.return_value.text = "This is the synthesized answer."
    mock_get_llm.return_value = mock_llm

    payload = {'message': 'What is a bill of lading?'}
    r = client.post('/api/chat', json=payload, headers=auth_headers)

    assert r.status_code == 200
    data = r.json()

    assert data.get('success') is True
    assert data.get('answer') == "This is the synthesized answer."
    # Raw data should NOT be in the top-level response.
    assert 'data' not in data
    # The message should not be echoed back.
    assert 'message' not in data

    mock_info_retriever.assert_called_once_with(
        'What is a bill of lading?',
        {'summary': ''},
        prefer_web=False,
        session_id=None,
    )
    mock_get_llm.assert_called_once()
    # Two calls now: one to classify intent, one to synthesize the answer.
    assert mock_llm.generate_content.call_count == 2