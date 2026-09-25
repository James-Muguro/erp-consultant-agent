"""
Integration tests for the orchestrator API.

Coverage:
  Auth lifecycle (signup, login response shape, /me, invalid tokens)
  Project CRUD (start, list, rename, archive, permanent delete)
  Per-user isolation (one user's session invisible to another)
  Health and readiness probes
  Error envelope shape and X-Request-ID correlation
  Chat and streaming chat (SSE)
  Phase execution with parameters
  Request body size limit

Fixtures:
  * client      a single TestClient per test, entered via context
                manager so the lifespan runs once and cleanly shuts
                down at the end.
  * auth_headers
                completes the full new auth flow (signup →
                verify-email → login → verify-otp) and returns Bearer
                headers. Each call = one signup + one login (two
                bcrypt operations ≈ 500ms) plus the flow's HTTP
                overhead. Tests needing two distinct users call it
                twice.

Notes on test behavior:
  * The new auth flow requires email verification and OTP-based MFA.
    The email abstraction is mocked during the flow via
    `set_email_provider`, matching tests/test_auth_lifecycle.py.
  * The `mock_info_retriever` in the chat tests returns
    `web_results` as a list of dicts, matching the pre-review
    info_retriever output shape. The mock is patched at the boundary,
    so the shape doesn't matter for these tests.
  * Signup requests include an explicit `account_type`. Every fixture
    and every inline signup uses `functional_consultant`, whose
    permission set covers the project-scoped operations these tests
    exercise.
"""
from __future__ import annotations

import json
import uuid
from typing import List, Tuple

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch

from src.config.settings import settings
from src.email import reset_email_provider, set_email_provider
from src.orchestrator_api import app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _reset_email_provider_after_test():
    yield
    reset_email_provider()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _complete_auth_flow(client: TestClient, email: str) -> str:
    """Run signup → verify-email → login → verify-otp and return the
    access token. The email abstraction is mocked for the duration so
    no SMTP connection is attempted."""
    captured: List[Tuple[str, str, str]] = []

    def _capture(to: str, subject: str, body: str) -> None:
        captured.append((to, subject, body))

    set_email_provider(_capture)
    try:
        r = client.post(
            "/api/auth/signup",
            json={
                "email": email,
                "password": "testpassword123",
                "account_type": "functional_consultant",
            },
        )
        assert r.status_code == 200, r.text

        verify_body = captured[-1][2]
        raw_verify = verify_body.split("token=")[1].split("\n")[0]
        r = client.post(
            "/api/auth/verify-email", json={"token": raw_verify}
        )
        assert r.status_code == 200, r.text

        r = client.post(
            "/api/auth/login",
            json={"email": email, "password": "testpassword123"},
        )
        assert r.status_code == 200, r.text
        pending_ref = r.json()["pending_auth_ref"]

        otp_body = captured[-1][2]
        otp_code = otp_body.split("    ")[1].split("\n")[0].strip()

        r = client.post(
            "/api/auth/login/verify-otp",
            json={"pending_auth_ref": pending_ref, "code": otp_code},
        )
        assert r.status_code == 200, r.text
        return r.json()["access_token"]
    finally:
        reset_email_provider()


def _new_user_headers(client: TestClient) -> dict:
    """Sign up a fresh, unique user, complete the full auth flow, and
    return Authorization headers."""
    email = f"test-{uuid.uuid4().hex[:12]}@example.com"
    token = _complete_auth_flow(client, email)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def auth_headers(client):
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
    def test_unconditional_security_headers_present_on_every_response(self, client):
        r = client.get('/api/auth/me')
        assert r.headers.get('X-Content-Type-Options') == 'nosniff'
        assert r.headers.get('X-Frame-Options') == 'DENY'
        assert r.headers.get('Referrer-Policy') == 'strict-origin-when-cross-origin'
        assert 'geolocation=()' in r.headers.get('Permissions-Policy', '')

    def test_hsts_is_absent_on_plain_http(self, client):
        r = client.get('/health')
        assert 'Strict-Transport-Security' not in r.headers

    def test_hsts_is_present_when_forwarded_proto_is_https(self, client):
        r = client.get(
            '/health',
            headers={'X-Forwarded-Proto': 'https'},
        )
        assert 'max-age=' in r.headers.get('Strict-Transport-Security', '')

    def test_hsts_present_on_unauthenticated_response_over_https(self, client):
        r = client.get(
            '/api/auth/me',
            headers={'X-Forwarded-Proto': 'https'},
        )
        assert r.status_code == 401
        assert 'max-age=' in r.headers.get('Strict-Transport-Security', '')


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def test_signup_returns_generic_message_and_login_starts_mfa(client):
    """Current contract:
      * /signup returns a generic MessageResponse; no tokens.
      * /login returns a pending_auth_ref; no tokens.
      * Token acquisition requires /login/verify-otp."""
    email = f"test-{uuid.uuid4().hex[:12]}@example.com"

    captured: List[Tuple[str, str, str]] = []
    set_email_provider(lambda t, s, b: captured.append((t, s, b)))
    try:
        signup_payload = {
            'email': email,
            'password': 'testpassword123',
            'account_type': 'functional_consultant',
        }

        r = client.post('/api/auth/signup', json=signup_payload)
        assert r.status_code == 200, r.text
        body = r.json()
        assert 'message' in body
        assert 'access_token' not in body
        assert 'refresh_token' not in body

        # Duplicate signup returns an identical generic response.
        r = client.post('/api/auth/signup', json=signup_payload)
        assert r.status_code == 200, r.text

        # The verification email was sent for the first signup.
        verify_body = captured[-1][2]
        raw_verify = verify_body.split("token=")[1].split("\n")[0]
        r = client.post(
            '/api/auth/verify-email', json={"token": raw_verify},
        )
        assert r.status_code == 200, r.text

        # Login returns pending_auth_ref, not a token.
        r = client.post(
            '/api/auth/login',
            json={'email': email, 'password': 'testpassword123'},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert 'pending_auth_ref' in body
        assert 'access_token' not in body

        # Wrong password returns 401 with the generic message.
        r = client.post(
            '/api/auth/login',
            json={'email': email, 'password': 'wrongpassword'},
        )
        assert r.status_code == 401

        # Complete the flow: extract OTP, verify, get a token.
        pending_ref = body['pending_auth_ref']
        otp_body = captured[-1][2]
        otp_code = otp_body.split("    ")[1].split("\n")[0].strip()
        r = client.post(
            '/api/auth/login/verify-otp',
            json={'pending_auth_ref': pending_ref, 'code': otp_code},
        )
        assert r.status_code == 200, r.text
        login_token = r.json()['access_token']
    finally:
        reset_email_provider()

    # /me works with a valid token.
    r = client.get(
        '/api/auth/me', headers={'Authorization': f'Bearer {login_token}'},
    )
    assert r.status_code == 200
    body = r.json()
    assert body['email'] == email
    assert body['roles'] == ['functional_consultant']
    assert body['organizations'] == []

    # /me rejects a missing token.
    r = client.get('/api/auth/me')
    assert r.status_code == 401

    # /me rejects an invalid token.
    r = client.get(
        '/api/auth/me', headers={'Authorization': 'Bearer not-a-real-token'},
    )
    assert r.status_code == 401


def test_signup_rejects_short_password(client):
    email = f"test-{uuid.uuid4().hex[:12]}@example.com"
    r = client.post(
        '/api/auth/signup',
        json={
            'email': email,
            'password': 'a',
            'account_type': 'functional_consultant',
        },
    )
    assert r.status_code == 422


def test_signup_rejects_common_password(client):
    email = f"test-{uuid.uuid4().hex[:12]}@example.com"
    r = client.post(
        '/api/auth/signup',
        json={
            'email': email,
            'password': 'password1234',
            'account_type': 'functional_consultant',
        },
    )
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
    assert 'next_action' in data


def test_start_project_requires_auth(client):
    payload = {'project_name': 'Test Project', 'module': 'FI'}
    r = client.post('/api/projects/start', json=payload)
    assert r.status_code == 401


def test_project_isolated_between_users(client):
    headers_a = _new_user_headers(client)
    headers_b = _new_user_headers(client)

    r = client.post(
        '/api/projects/start',
        json={'project_name': 'Owned by A', 'module': 'FI'},
        headers=headers_a,
    )
    session_id = r.json()['session_id']

    r = client.get(f'/api/projects/{session_id}/status', headers=headers_a)
    assert r.status_code == 200

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

    r = client.delete(f'/api/projects/{session_id}', headers=auth_headers)
    assert r.status_code == 409

    r = client.get('/api/projects', headers=auth_headers)
    ids = {p['session_id'] for p in r.json()['projects']}
    assert session_id not in ids

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

    r = client.post(
        '/api/feedback',
        json={'session_id': session_id, 'rating': 7},
        headers=auth_headers,
    )
    assert r.status_code == 422

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
    r = client.get('/api/auth/me')
    assert r.status_code == 401
    body = r.json()
    assert 'error' in body
    assert body['error']['code'] == 401
    assert 'message' in body['error']
    assert 'request_id' in body['error']
    assert r.headers.get('X-Request-ID') == body['error']['request_id']


def test_request_id_is_honored_from_header(client):
    r = client.get('/api/auth/me', headers={'X-Request-ID': 'caller-supplied-id'})
    assert r.headers.get('X-Request-ID') == 'caller-supplied-id'
    assert r.json()['error']['request_id'] == 'caller-supplied-id'


# ---------------------------------------------------------------------------
# Phase execution with parameters
# ---------------------------------------------------------------------------
class TestPhaseExecutionWithBody:
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
# Request body size limit
# ---------------------------------------------------------------------------
def test_oversized_request_body_is_rejected(client, auth_headers):
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
    mock_info_retriever.return_value = {
        'decision': {'decision': 'web', 'confidence': 0.9, 'reasoning': 'Query is a question.'},
        'kb_results': [],
        'web_results': [{'title': 'Test Result', 'snippet': 'A snippet.'}],
    }

    mock_llm = MagicMock()
    mock_llm.generate_content.return_value.text = "Streamed synthesized answer."
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
    assert 'data' not in data
    assert 'message' not in data

    mock_info_retriever.assert_called_once_with(
        'What is a bill of lading?',
        {'summary': ''},
        prefer_web=False,
        session_id=None,
    )
    mock_get_llm.assert_called_once()
    assert mock_llm.generate_content.call_count == 2