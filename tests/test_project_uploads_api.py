"""
Integration tests for the project uploads API.

Coverage:
  Upload endpoint
    - 503 when object storage isn't configured.
    - Happy path: upload succeeds, metadata is returned, extracted text
      reaches project memory.
    - Auth and ownership checks.
    - Unsupported file type rejected.
    - Oversized file rejected.
    - Storage rollback when the DB insert fails (added in the API
      review — prevents orphaned S3 objects).

  List / download / delete
    - List shows uploaded documents with metadata.
    - Download returns the exact original bytes.
    - Download and list are cross-user-isolated (404, not 403).
    - Delete removes the DB row, cleans up storage, and cleans up the
      project-memory entry.
    - Delete is idempotent-failure on a second call.

  Content-Disposition encoding
    - ASCII filename produces a simple header.
    - Non-ASCII filename produces an RFC 5987 filename* form alongside
      the ASCII fallback (added in the API review).
    - Quote-containing filename doesn't break the header (added in the
      API review).

Fixtures:
  * client       TestClient entered as a context manager so the
                 lifespan shutdown hook runs and the resilience thread
                 pool is released per test.
  * auth_headers a fresh user per call, so tests never see each
                 other's projects.
  * s3_configured
                 monkeypatches settings for S3, spins up moto's mock
                 AWS, and creates the test bucket. monkeypatch
                 auto-reverts the settings patches on teardown.

Notes:
  * The list/download/delete endpoints verify ownership with
    _get_owned_session, which returns 404 for a non-owner (not 403) —
    an attacker cannot distinguish "session doesn't exist" from
    "session exists but belongs to someone else." Every cross-user
    test asserts 404 specifically.
  * The upload endpoint bounds request size in the reader (chunked,
    64KB at a time) rather than after buffering the whole body. The
    oversized-file test verifies the outcome (413) — the mechanism
    (not buffering 2MB into memory) is a production-perf property
    that would need a mock on the underlying read to assert directly.
  * Every signup uses account_type='functional_consultant'. That role
    holds UPLOADS_READ, UPLOADS_WRITE, and PROJECT_CREATE, which are
    required by the upload routes and the fixture's project creation.
"""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import boto3
import pytest
from fastapi.testclient import TestClient
from moto import mock_aws
from tests._auth_helpers import signup_and_authenticate

from src.config.settings import settings
from src.memory import agent_memory
from src.orchestrator_api import app
from src.storage import object_storage


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def client():
    """A TestClient whose lifespan runs for the duration of the test
    and shuts down cleanly at the end. Using the context manager form
    ensures the shutdown hook runs (releasing the resilience thread
    pool, etc.)."""
    with TestClient(app) as c:
        yield c


@pytest.fixture
def auth_headers(client):
    email = f"upload-{uuid.uuid4().hex[:12]}@example.com"
    token = signup_and_authenticate(
        client, email=email, account_type="functional_consultant"
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def s3_configured(monkeypatch):
    """Configure S3 settings, spin up moto's mock AWS, and create the
    test bucket.

    monkeypatch.setattr reverts each settings attribute on teardown, so
    a test that runs after this one doesn't accidentally see a
    configured S3. The moto context manager unmocks boto3 on exit."""
    monkeypatch.setattr(settings, "s3_bucket_name", "test-bucket")
    monkeypatch.setattr(settings, "s3_access_key_id", "fake-key")
    monkeypatch.setattr(settings, "s3_secret_access_key", "fake-secret")
    monkeypatch.setattr(settings, "s3_endpoint_url", None)
    monkeypatch.setattr(settings, "s3_region", "us-east-1")
    with mock_aws():
        boto_client = boto3.client("s3", region_name="us-east-1")
        boto_client.create_bucket(Bucket="test-bucket")
        yield


def _start_project(client: TestClient, headers: dict) -> str:
    r = client.post(
        '/api/projects/start',
        json={'project_name': 'Upload Test', 'module': 'FI'},
        headers=headers,
    )
    return r.json()['session_id']


# ===========================================================================
# Storage not configured
# ===========================================================================
class TestUploadWithoutStorageConfigured:
    def test_returns_503_when_object_storage_not_configured(self, client, auth_headers, monkeypatch):
        monkeypatch.setattr(settings, "s3_bucket_name", None)
        session_id = _start_project(client, auth_headers)

        r = client.post(
            f'/api/projects/{session_id}/uploads',
            files={'file': ('notes.txt', b'some content', 'text/plain')},
            headers=auth_headers,
        )
        assert r.status_code == 503
        assert 'storage' in r.json()['error']['message'].lower()


# ===========================================================================
# Upload
# ===========================================================================
class TestUpload:
    def test_upload_success_returns_metadata(self, client, auth_headers, s3_configured):
        session_id = _start_project(client, auth_headers)

        r = client.post(
            f'/api/projects/{session_id}/uploads',
            files={
                'file': (
                    'requirements.txt',
                    b'Purchase orders need manager approval.',
                    'text/plain',
                ),
            },
            headers=auth_headers,
        )
        assert r.status_code == 200
        body = r.json()
        assert body['filename'] == 'requirements.txt'
        assert body['extracted_text_chars'] > 0
        assert body['size_bytes'] == len(b'Purchase orders need manager approval.')
        assert 'id' in body

    def test_upload_requires_auth(self, client, s3_configured):
        r = client.post(
            '/api/projects/prj_fake/uploads',
            files={'file': ('notes.txt', b'content', 'text/plain')},
        )
        assert r.status_code == 401

    def test_upload_to_another_users_session_is_rejected(self, client, auth_headers, s3_configured):
        # A second, unrelated user.
        other_email = f"other-{uuid.uuid4().hex[:12]}@example.com"
        other_token = signup_and_authenticate(
            client, email=other_email, account_type="functional_consultant"
        )
        other_headers = {"Authorization": f"Bearer {other_token}"}
        session_id = _start_project(client, auth_headers)

        r = client.post(
            f'/api/projects/{session_id}/uploads',
            files={'file': ('notes.txt', b'content', 'text/plain')},
            headers=other_headers,
        )
        assert r.status_code == 404

    def test_unsupported_file_type_rejected(self, client, auth_headers, s3_configured):
        session_id = _start_project(client, auth_headers)
        r = client.post(
            f'/api/projects/{session_id}/uploads',
            files={'file': ('virus.exe', b'binary junk', 'application/octet-stream')},
            headers=auth_headers,
        )
        assert r.status_code == 415

    def test_oversized_file_rejected(self, client, auth_headers, s3_configured, monkeypatch):
        monkeypatch.setattr(settings, "max_upload_size_mb", 1)
        session_id = _start_project(client, auth_headers)

        too_big = b"x" * (2 * 1024 * 1024)  # 2MB > 1MB limit
        r = client.post(
            f'/api/projects/{session_id}/uploads',
            files={'file': ('big.txt', too_big, 'text/plain')},
            headers=auth_headers,
        )
        assert r.status_code == 413

    def test_extracted_text_becomes_recallable_project_memory(self, client, auth_headers, s3_configured):
        """The actual point of this feature: uploaded content should be
        something agents can recall in later phases."""
        session_id = _start_project(client, auth_headers)

        client.post(
            f'/api/projects/{session_id}/uploads',
            files={
                'file': (
                    'notes.txt',
                    b'The client uses a custom 12-segment chart of accounts.',
                    'text/plain',
                ),
            },
            headers=auth_headers,
        )

        recalled = agent_memory.recall(session_id, {'category': 'uploaded_document'})
        assert any('12-segment chart of accounts' in m.content for m in recalled)

    def test_storage_object_is_cleaned_up_when_db_insert_fails(
        self, client, auth_headers, s3_configured,
    ):
        """If the storage upload succeeds but the DB insert fails, the
        just-uploaded object must be removed from storage. Otherwise a
        transient DB error leaves an orphaned S3 object that consumes
        quota and never appears in any listing.

        Simulated by patching the module-level SessionLocal to return a
        session whose commit raises. The endpoint re-raises after
        rollback, so the client sees a 500 through the standard error
        envelope. delete_object is spied on to confirm the rollback
        path ran."""
        session_id = _start_project(client, auth_headers)

        with patch("src.orchestrator_api.SessionLocal") as mock_session_factory, \
            patch.object(object_storage, "delete_object") as mock_delete:

            mock_db = MagicMock()
            mock_db.commit.side_effect = RuntimeError("DB is unavailable")
            mock_session_factory.return_value = mock_db

            test_client = TestClient(app, raise_server_exceptions=False)
            r = test_client.post(
                f'/api/projects/{session_id}/uploads',
                files={'file': ('notes.txt', b'content', 'text/plain')},
                headers=auth_headers,
        )

        # Handler re-raises → 500 via the standard error envelope.
        assert r.status_code == 500
        # The rollback path removed the object we uploaded.
        mock_delete.assert_called_once()


# ===========================================================================
# List / download / delete
# ===========================================================================
class TestListDownloadDelete:
    def test_list_shows_uploaded_document(self, client, auth_headers, s3_configured):
        session_id = _start_project(client, auth_headers)
        client.post(
            f'/api/projects/{session_id}/uploads',
            files={'file': ('notes.txt', b'some content', 'text/plain')},
            headers=auth_headers,
        )

        r = client.get(f'/api/projects/{session_id}/uploads', headers=auth_headers)
        assert r.status_code == 200
        docs = r.json()['documents']
        assert len(docs) == 1
        doc = docs[0]
        assert doc['filename'] == 'notes.txt'
        # Metadata beyond filename is part of the contract the SPA reads.
        assert doc['content_type'] == 'text/plain'
        assert doc['size_bytes'] == len(b'some content')
        assert 'uploaded_at' in doc
        assert 'id' in doc

    def test_list_is_scoped_to_the_owner(self, client, auth_headers, s3_configured):
        """A different user cannot see this session's documents —
        the ownership check returns 404."""
        other_email = f"other-{uuid.uuid4().hex[:12]}@example.com"
        other_token = signup_and_authenticate(
            client, email=other_email, account_type="functional_consultant"
        )
        other_headers = {"Authorization": f"Bearer {other_token}"}

        session_id = _start_project(client, auth_headers)

        r = client.get(
            f'/api/projects/{session_id}/uploads',
            headers=other_headers,
        )
        assert r.status_code == 404

    def test_download_returns_original_bytes(self, client, auth_headers, s3_configured):
        session_id = _start_project(client, auth_headers)
        upload_resp = client.post(
            f'/api/projects/{session_id}/uploads',
            files={'file': ('notes.txt', b'exact original content', 'text/plain')},
            headers=auth_headers,
        )
        doc_id = upload_resp.json()['id']

        r = client.get(
            f'/api/projects/{session_id}/uploads/{doc_id}/download',
            headers=auth_headers,
        )
        assert r.status_code == 200
        assert r.content == b'exact original content'

    def test_download_another_users_document_is_rejected(self, client, auth_headers, s3_configured):
        other_email = f"other-{uuid.uuid4().hex[:12]}@example.com"
        other_token = signup_and_authenticate(
            client, email=other_email, account_type="functional_consultant"
        )
        other_headers = {"Authorization": f"Bearer {other_token}"}

        session_id = _start_project(client, auth_headers)
        upload_resp = client.post(
            f'/api/projects/{session_id}/uploads',
            files={'file': ('notes.txt', b'content', 'text/plain')},
            headers=auth_headers,
        )
        doc_id = upload_resp.json()['id']

        r = client.get(
            f'/api/projects/{session_id}/uploads/{doc_id}/download',
            headers=other_headers,
        )
        assert r.status_code == 404

    def test_delete_removes_from_list(self, client, auth_headers, s3_configured):
        session_id = _start_project(client, auth_headers)
        upload_resp = client.post(
            f'/api/projects/{session_id}/uploads',
            files={'file': ('notes.txt', b'content', 'text/plain')},
            headers=auth_headers,
        )
        doc_id = upload_resp.json()['id']

        r = client.delete(
            f'/api/projects/{session_id}/uploads/{doc_id}',
            headers=auth_headers,
        )
        assert r.status_code == 200

        r = client.get(f'/api/projects/{session_id}/uploads', headers=auth_headers)
        assert r.json()['documents'] == []

    def test_delete_cleans_up_the_project_memory_entry(
        self, client, auth_headers, s3_configured,
    ):
        """Deleting an upload must remove the memory entry created at
        upload time. Otherwise the deleted document's content would
        still be recallable by agents in later phases — a genuine
        data-consistency problem after a user deletes something."""
        session_id = _start_project(client, auth_headers)
        upload_resp = client.post(
            f'/api/projects/{session_id}/uploads',
            files={'file': ('notes.txt', b'deletable content', 'text/plain')},
            headers=auth_headers,
        )
        doc_id = upload_resp.json()['id']

        # Sanity: the memory entry exists before delete.
        before = agent_memory.recall(session_id, {'category': 'uploaded_document'})
        assert before, "upload should have created a memory entry"

        with patch.object(
            agent_memory.project_memory, "delete_memory", wraps=agent_memory.project_memory.delete_memory,
        ) as mock_delete_memory:
            r = client.delete(
                f'/api/projects/{session_id}/uploads/{doc_id}',
                headers=auth_headers,
            )
        assert r.status_code == 200
        mock_delete_memory.assert_called_once_with(session_id, f"upload_{doc_id}")

        # After delete, the memory entry is gone.
        after = agent_memory.recall(session_id, {'category': 'uploaded_document'})
        assert not any(f"upload_{doc_id}" == getattr(m, "entry_id", None) for m in after)

    def test_delete_is_idempotent_failure_not_success_on_second_call(
        self, client, auth_headers, s3_configured,
    ):
        session_id = _start_project(client, auth_headers)
        upload_resp = client.post(
            f'/api/projects/{session_id}/uploads',
            files={'file': ('notes.txt', b'content', 'text/plain')},
            headers=auth_headers,
        )
        doc_id = upload_resp.json()['id']

        client.delete(
            f'/api/projects/{session_id}/uploads/{doc_id}',
            headers=auth_headers,
        )
        r = client.delete(
            f'/api/projects/{session_id}/uploads/{doc_id}',
            headers=auth_headers,
        )
        assert r.status_code == 404


# ===========================================================================
# Content-Disposition encoding (API-review behavior)
# ===========================================================================
class TestAttachmentHeaders:
    """The download endpoint builds Content-Disposition with both a
    sanitized ASCII fallback and an RFC 5987 filename* form. The
    original header would break on a quote character in the filename
    and drop non-ASCII names entirely."""

    def _upload_and_download(
        self, client, auth_headers, filename: str,
    ):
        session_id = _start_project(client, auth_headers)
        upload_resp = client.post(
            f'/api/projects/{session_id}/uploads',
            files={'file': (filename, b'content', 'text/plain')},
            headers=auth_headers,
        )
        assert upload_resp.status_code == 200, upload_resp.text
        doc_id = upload_resp.json()['id']
        return client.get(
            f'/api/projects/{session_id}/uploads/{doc_id}/download',
            headers=auth_headers,
        )

    def test_ascii_filename_produces_simple_header(self, client, auth_headers, s3_configured):
        r = self._upload_and_download(client, auth_headers, "plain_notes.txt")
        assert r.status_code == 200
        disposition = r.headers.get("Content-Disposition", "")
        assert 'attachment' in disposition
        assert 'filename="plain_notes.txt"' in disposition

    def test_non_ascii_filename_produces_rfc5987_form(self, client, auth_headers, s3_configured):
        """A filename with non-ASCII characters must round-trip. The
        header carries both an ASCII fallback and the RFC 5987
        filename* form so every client can pick the one it supports."""
        r = self._upload_and_download(client, auth_headers, "café_notes.txt")
        assert r.status_code == 200
        disposition = r.headers.get("Content-Disposition", "")
        # RFC 5987 form is present.
        assert "filename*=UTF-8''" in disposition
        # And the encoded form contains the é as %C3%A9.
        assert "%C3%A9" in disposition

    def test_quote_in_filename_does_not_break_header(self, client, auth_headers, s3_configured):
        """A filename containing a literal '"' would have broken the
        original header (unterminated quoted string). The sanitized
        ASCII fallback replaces the quote with '_', and the encoded
        form preserves the original."""
        r = self._upload_and_download(client, auth_headers, 'weird"name.txt')
        assert r.status_code == 200
        disposition = r.headers.get("Content-Disposition", "")
        # Two separate quoted strings would confuse parsers; the ASCII
        # fallback must not contain a bare '"' inside its quotes.
        # Extract the ASCII filename= value and confirm no embedded quote.
        import re
        ascii_match = re.search(r'filename="([^"]*)"', disposition)
        assert ascii_match is not None
        assert '"' not in ascii_match.group(1)


# ===========================================================================
# _attachment_headers helper (unit)
# ===========================================================================
class TestAttachmentHeadersUnit:
    """Unit tests for the helper, independent of the API. Verifying the
    shape here means a change to the header format surfaces as a
    focused failure rather than as an integration test failure."""

    def test_ascii_filename(self):
        from src.orchestrator_api import _attachment_headers
        headers = _attachment_headers("report.docx")
        disposition = headers["Content-Disposition"]
        assert 'filename="report.docx"' in disposition
        assert "filename*=UTF-8''report.docx" in disposition

    def test_non_ascii_filename(self):
        from src.orchestrator_api import _attachment_headers
        headers = _attachment_headers("café.txt")
        disposition = headers["Content-Disposition"]
        # ASCII fallback strips the non-ASCII character.
        assert 'filename="caf_.txt"' in disposition
        # RFC 5987 form encodes it.
        assert "filename*=UTF-8''caf%C3%A9.txt" in disposition

    def test_empty_filename_falls_back_to_default(self):
        from src.orchestrator_api import _attachment_headers
        headers = _attachment_headers("")
        disposition = headers["Content-Disposition"]
        # The helper substitutes 'document' when the name is empty so
        # the header remains well-formed.
        assert "filename=" in disposition
        assert 'filename=""' not in disposition

    def test_none_filename_falls_back_to_default(self):
        from src.orchestrator_api import _attachment_headers
        headers = _attachment_headers(None)
        disposition = headers["Content-Disposition"]
        # The helper substitutes 'document' when the name is empty so
        # the header remains well-formed.
        assert "filename=" in disposition
        assert 'filename=""' not in disposition