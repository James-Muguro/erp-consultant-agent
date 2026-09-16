import uuid
from fastapi.testclient import TestClient

from src.orchestrator_api import app
from src.db.base import SessionLocal
from src.db.models import SolutionDecision


def _auth_headers(client: TestClient) -> dict:
    email = f"test-{uuid.uuid4().hex[:12]}@example.com"
    r = client.post('/api/auth/signup', json={'email': email, 'password': 'testpassword123'})
    assert r.status_code == 200, r.text
    token = r.json()['access_token']
    return {'Authorization': f'Bearer {token}'}


def test_consistency_check_requires_auth():
    client = TestClient(app)
    r = client.post('/api/projects/prj_fake/consistency-check')
    assert r.status_code == 401


def test_consistency_check_requires_ownership():
    client = TestClient(app)
    headers_a = _auth_headers(client)
    headers_b = _auth_headers(client)
    r = client.post('/api/projects/start', json={'project_name': 'CC Test', 'module': 'FI'}, headers=headers_a)
    session_id = r.json()['session_id']

    r = client.post(f'/api/projects/{session_id}/consistency-check', headers=headers_b)
    assert r.status_code == 404


def test_consistency_check_finds_and_returns_a_real_contradiction():
    client = TestClient(app)
    headers = _auth_headers(client)
    r = client.post('/api/projects/start',
                     json={'project_name': 'CC Test', 'module': 'FI', 'erp_system': 'SAP S/4HANA'},
                     headers=headers)
    session_id = r.json()['session_id']

    db = SessionLocal()
    db.add(SolutionDecision(
        id=uuid.uuid4().hex, session_id=session_id, decision_type='erp_selection',
        component='core', lineage_id=uuid.uuid4().hex, description='Recommend Oracle Fusion for this deployment',
    ))
    db.commit()
    db.close()

    r = client.post(f'/api/projects/{session_id}/consistency-check', headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body['findings_count'] == 1

    r = client.get(f'/api/projects/{session_id}/issues?status=open', headers=headers)
    assert any('Oracle' in i['description'] for i in r.json()['issues'])
