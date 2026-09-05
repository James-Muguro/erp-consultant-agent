import uuid

from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from src.orchestrator_api import app


def _auth_headers(client: TestClient) -> dict:
    """Sign up a fresh, unique user and return Authorization headers for
    them. Each test gets its own account so tests never see each other's
    projects."""
    email = f"test-{uuid.uuid4().hex[:12]}@example.com"
    r = client.post('/api/auth/signup', json={'email': email, 'password': 'testpassword123'})
    assert r.status_code == 200, r.text
    token = r.json()['access_token']
    return {'Authorization': f'Bearer {token}'}


def test_health():
    client = TestClient(app)
    r = client.get('/health')
    assert r.status_code == 200
    assert r.json()['status'] == 'ok'


def test_signup_login_me():
    client = TestClient(app)
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

    # /me rejects a missing/invalid token
    r = client.get('/api/auth/me')
    assert r.status_code == 401
    r = client.get('/api/auth/me', headers={'Authorization': 'Bearer not-a-real-token'})
    assert r.status_code == 401


def test_start_project_minimal():
    client = TestClient(app)
    headers = _auth_headers(client)
    payload = {'project_name': 'Test Project', 'module': 'FI'}
    r = client.post('/api/projects/start', json=payload, headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert data.get('success') is True
    assert 'session_id' in data


def test_start_project_requires_auth():
    client = TestClient(app)
    payload = {'project_name': 'Test Project', 'module': 'FI'}
    r = client.post('/api/projects/start', json=payload)
    assert r.status_code == 401


def test_project_isolated_between_users():
    """One user's session must be invisible (404, not 403) to another user."""
    client = TestClient(app)
    headers_a = _auth_headers(client)
    headers_b = _auth_headers(client)

    r = client.post('/api/projects/start', json={'project_name': 'Owned by A', 'module': 'FI'}, headers=headers_a)
    session_id = r.json()['session_id']

    # Owner can read their own session
    r = client.get(f'/api/projects/{session_id}/status', headers=headers_a)
    assert r.status_code == 200

    # A different user gets 404, not the project's data
    r = client.get(f'/api/projects/{session_id}/status', headers=headers_b)
    assert r.status_code == 404


def test_list_projects_scoped_to_user():
    client = TestClient(app)
    headers_a = _auth_headers(client)
    headers_b = _auth_headers(client)

    client.post('/api/projects/start', json={'project_name': 'A Project 1', 'module': 'FI'}, headers=headers_a)
    client.post('/api/projects/start', json={'project_name': 'A Project 2', 'module': 'MM'}, headers=headers_a)
    client.post('/api/projects/start', json={'project_name': 'B Project 1', 'module': 'SD'}, headers=headers_b)

    r = client.get('/api/projects', headers=headers_a)
    assert r.status_code == 200
    names = {p['project_name'] for p in r.json()['projects']}
    assert names == {'A Project 1', 'A Project 2'}


@patch('src.orchestrator_api.info_retriever')
@patch('src.utils.llm.get_llm')
def test_chat_end_to_end(mock_get_llm, mock_info_retriever):
    """
    Ensure the /api/chat endpoint returns a synthesized answer, not raw data.
    """
    client = TestClient(app)
    headers = _auth_headers(client)

    # 1. Mock the internal tools
    # Mock info_retriever to return sample web results
    mock_info_retriever.return_value = {
        'decision': {'decision': 'web', 'confidence': 0.9, 'reasoning': 'Query is a question.'},
        'kb_results': [],
        'web_results': [
            {'title': 'Test Result', 'snippet': 'This is a test snippet from the web.'}
        ]
    }

    # Mock the LLM's response
    mock_llm = MagicMock()
    mock_llm.generate_content.return_value.text = "This is the synthesized answer."
    mock_get_llm.return_value = mock_llm

    # 2. Call the API
    payload = {'message': 'What is a bill of lading?'}
    r = client.post('/api/chat', json=payload, headers=headers)

    # 3. Assert the response
    assert r.status_code == 200
    data = r.json()

    assert data.get('success') is True
    # The final answer should be the synthesized one
    assert data.get('answer') == "This is the synthesized answer."
    # Raw data should NOT be in the top-level response
    assert 'data' not in data
    # The message should not be returned
    assert 'message' not in data
    
    # Ensure the correct mocks were called
    mock_info_retriever.assert_called_once_with('What is a bill of lading?', {'summary': ''}, prefer_web=False)
    mock_get_llm.assert_called_once()
    # Two calls now: one to classify intent, one to synthesize the answer
    assert mock_llm.generate_content.call_count == 2
