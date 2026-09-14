import uuid
import pytest
from fastapi.testclient import TestClient
from moto import mock_aws
import boto3

from src.orchestrator_api import app
from src.config.settings import settings
from src.memory import agent_memory


def _auth_headers(client: TestClient) -> dict:
    email = f"test-{uuid.uuid4().hex[:12]}@example.com"
    r = client.post('/api/auth/signup', json={'email': email, 'password': 'testpassword123'})
    assert r.status_code == 200, r.text
    token = r.json()['access_token']
    return {'Authorization': f'Bearer {token}'}


@pytest.fixture
def s3_configured(monkeypatch):
    monkeypatch.setattr(settings, "s3_bucket_name", "test-bucket")
    monkeypatch.setattr(settings, "s3_access_key_id", "fake-key")
    monkeypatch.setattr(settings, "s3_secret_access_key", "fake-secret")
    monkeypatch.setattr(settings, "s3_endpoint_url", None)
    monkeypatch.setattr(settings, "s3_region", "us-east-1")
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="test-bucket")
        yield


def _start_project(client, headers):
    r = client.post('/api/projects/start', json={'project_name': 'Upload Test', 'module': 'FI'}, headers=headers)
    return r.json()['session_id']


class TestUploadWithoutStorageConfigured:
    def test_returns_503_when_object_storage_not_configured(self, monkeypatch):
        monkeypatch.setattr(settings, "s3_bucket_name", None)
        client = TestClient(app)
        headers = _auth_headers(client)
        session_id = _start_project(client, headers)

        r = client.post(
            f'/api/projects/{session_id}/uploads',
            files={'file': ('notes.txt', b'some content', 'text/plain')},
            headers=headers,
        )
        assert r.status_code == 503


class TestUpload:
    def test_upload_success_returns_metadata(self, s3_configured):
        client = TestClient(app)
        headers = _auth_headers(client)
        session_id = _start_project(client, headers)

        r = client.post(
            f'/api/projects/{session_id}/uploads',
            files={'file': ('requirements.txt', b'Purchase orders need manager approval.', 'text/plain')},
            headers=headers,
        )
        assert r.status_code == 200
        body = r.json()
        assert body['filename'] == 'requirements.txt'
        assert body['extracted_text_chars'] > 0

    def test_upload_requires_auth(self, s3_configured):
        client = TestClient(app)
        r = client.post(
            '/api/projects/prj_fake/uploads',
            files={'file': ('notes.txt', b'content', 'text/plain')},
        )
        assert r.status_code == 401

    def test_upload_to_another_users_session_is_rejected(self, s3_configured):
        client = TestClient(app)
        headers_a = _auth_headers(client)
        headers_b = _auth_headers(client)
        session_id = _start_project(client, headers_a)

        r = client.post(
            f'/api/projects/{session_id}/uploads',
            files={'file': ('notes.txt', b'content', 'text/plain')},
            headers=headers_b,
        )
        assert r.status_code == 404

    def test_unsupported_file_type_rejected(self, s3_configured):
        client = TestClient(app)
        headers = _auth_headers(client)
        session_id = _start_project(client, headers)

        r = client.post(
            f'/api/projects/{session_id}/uploads',
            files={'file': ('virus.exe', b'binary junk', 'application/octet-stream')},
            headers=headers,
        )
        assert r.status_code == 415

    def test_oversized_file_rejected(self, s3_configured, monkeypatch):
        monkeypatch.setattr(settings, "max_upload_size_mb", 1)
        client = TestClient(app)
        headers = _auth_headers(client)
        session_id = _start_project(client, headers)

        too_big = b"x" * (2 * 1024 * 1024)  # 2MB > 1MB limit
        r = client.post(
            f'/api/projects/{session_id}/uploads',
            files={'file': ('big.txt', too_big, 'text/plain')},
            headers=headers,
        )
        assert r.status_code == 413

    def test_extracted_text_becomes_recallable_project_memory(self, s3_configured):
        """The actual point of this feature: uploaded content should be
        something agents can recall in later phases."""
        client = TestClient(app)
        headers = _auth_headers(client)
        session_id = _start_project(client, headers)

        client.post(
            f'/api/projects/{session_id}/uploads',
            files={'file': ('notes.txt', b'The client uses a custom 12-segment chart of accounts.', 'text/plain')},
            headers=headers,
        )

        recalled = agent_memory.recall(session_id, {'category': 'uploaded_document'})
        assert any('12-segment chart of accounts' in m.content for m in recalled)


class TestListDownloadDelete:
    def test_list_shows_uploaded_document(self, s3_configured):
        client = TestClient(app)
        headers = _auth_headers(client)
        session_id = _start_project(client, headers)
        client.post(
            f'/api/projects/{session_id}/uploads',
            files={'file': ('notes.txt', b'some content', 'text/plain')},
            headers=headers,
        )

        r = client.get(f'/api/projects/{session_id}/uploads', headers=headers)
        assert r.status_code == 200
        docs = r.json()['documents']
        assert len(docs) == 1
        assert docs[0]['filename'] == 'notes.txt'

    def test_download_returns_original_bytes(self, s3_configured):
        client = TestClient(app)
        headers = _auth_headers(client)
        session_id = _start_project(client, headers)
        upload_resp = client.post(
            f'/api/projects/{session_id}/uploads',
            files={'file': ('notes.txt', b'exact original content', 'text/plain')},
            headers=headers,
        )
        doc_id = upload_resp.json()['id']

        r = client.get(f'/api/projects/{session_id}/uploads/{doc_id}/download', headers=headers)
        assert r.status_code == 200
        assert r.content == b'exact original content'

    def test_download_another_users_document_is_rejected(self, s3_configured):
        client = TestClient(app)
        headers_a = _auth_headers(client)
        headers_b = _auth_headers(client)
        session_id = _start_project(client, headers_a)
        upload_resp = client.post(
            f'/api/projects/{session_id}/uploads',
            files={'file': ('notes.txt', b'content', 'text/plain')},
            headers=headers_a,
        )
        doc_id = upload_resp.json()['id']

        r = client.get(f'/api/projects/{session_id}/uploads/{doc_id}/download', headers=headers_b)
        assert r.status_code == 404

    def test_delete_removes_from_list(self, s3_configured):
        client = TestClient(app)
        headers = _auth_headers(client)
        session_id = _start_project(client, headers)
        upload_resp = client.post(
            f'/api/projects/{session_id}/uploads',
            files={'file': ('notes.txt', b'content', 'text/plain')},
            headers=headers,
        )
        doc_id = upload_resp.json()['id']

        r = client.delete(f'/api/projects/{session_id}/uploads/{doc_id}', headers=headers)
        assert r.status_code == 200

        r = client.get(f'/api/projects/{session_id}/uploads', headers=headers)
        assert r.json()['documents'] == []

    def test_delete_is_idempotent_failure_not_success_on_second_call(self, s3_configured):
        client = TestClient(app)
        headers = _auth_headers(client)
        session_id = _start_project(client, headers)
        upload_resp = client.post(
            f'/api/projects/{session_id}/uploads',
            files={'file': ('notes.txt', b'content', 'text/plain')},
            headers=headers,
        )
        doc_id = upload_resp.json()['id']

        client.delete(f'/api/projects/{session_id}/uploads/{doc_id}', headers=headers)
        r = client.delete(f'/api/projects/{session_id}/uploads/{doc_id}', headers=headers)
        assert r.status_code == 404
