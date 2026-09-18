import uuid
from fastapi.testclient import TestClient

from src.orchestrator_api import app


def _auth_headers(client: TestClient) -> dict:
    email = f"test-{uuid.uuid4().hex[:12]}@example.com"
    r = client.post('/api/auth/signup', json={'email': email, 'password': 'testpassword123'})
    assert r.status_code == 200, r.text
    token = r.json()['access_token']
    return {'Authorization': f'Bearer {token}'}


def test_report_requires_auth():
    client = TestClient(app)
    r = client.post('/api/projects/prj_fake/report')
    assert r.status_code == 401


def test_report_requires_ownership():
    client = TestClient(app)
    headers_a = _auth_headers(client)
    headers_b = _auth_headers(client)
    r = client.post('/api/projects/start', json={'project_name': 'Report Test', 'module': 'FI'}, headers=headers_a)
    session_id = r.json()['session_id']

    r = client.post(f'/api/projects/{session_id}/report', headers=headers_b)
    assert r.status_code == 404


def test_report_generates_and_becomes_downloadable():
    client = TestClient(app)
    headers = _auth_headers(client)
    r = client.post('/api/projects/start',
                     json={'project_name': 'Report Test', 'module': 'FI', 'erp_system': 'SAP S/4HANA'},
                     headers=headers)
    session_id = r.json()['session_id']

    r = client.post(f'/api/projects/{session_id}/report', headers=headers)
    assert r.status_code == 200
    filename = r.json()['filename']
    assert filename.endswith('.docx')

    # Shows up in the existing generic documents list, no new list endpoint
    r = client.get(f'/api/projects/{session_id}/documents', headers=headers)
    assert any(d['filename'] == filename for d in r.json()['documents'])

    # Downloadable through the existing generic download endpoint
    r = client.get(f'/api/projects/{session_id}/documents/{filename}', headers=headers)
    assert r.status_code == 200
    assert r.headers['content-type'] == 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    assert len(r.content) > 0


def test_report_for_nonexistent_session_returns_404():
    client = TestClient(app)
    headers = _auth_headers(client)
    r = client.post('/api/projects/prj_does_not_exist/report', headers=headers)
    assert r.status_code == 404
