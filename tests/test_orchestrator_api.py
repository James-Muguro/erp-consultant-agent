from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from src.orchestrator_api import app
from src.config.settings import settings

AUTH_HEADERS = {'X-API-Key': settings.api_auth_key}


def test_health():
    client = TestClient(app)
    r = client.get('/health')
    assert r.status_code == 200
    assert r.json()['status'] == 'ok'


def test_start_project_minimal():
    client = TestClient(app)
    payload = {'project_name': 'Test Project', 'module': 'FI'}
    r = client.post('/api/projects/start', json=payload, headers=AUTH_HEADERS)
    assert r.status_code == 200
    data = r.json()
    assert data.get('success') is True
    assert 'session_id' in data


@patch('src.orchestrator_api.info_retriever')
@patch('src.utils.llm.get_llm')
def test_chat_end_to_end(mock_get_llm, mock_info_retriever):
    """
    Ensure the /api/chat endpoint returns a synthesized answer, not raw data.
    """
    client = TestClient(app)

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
    r = client.post('/api/chat', json=payload, headers=AUTH_HEADERS)

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
    mock_llm.generate_content.assert_called_once()

