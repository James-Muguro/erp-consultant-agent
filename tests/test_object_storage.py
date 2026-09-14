import pytest
from moto import mock_aws
import boto3

from src.storage import object_storage
from src.config.settings import settings


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


def test_not_configured_raises_clear_error(monkeypatch):
    monkeypatch.setattr(settings, "s3_bucket_name", None)
    with pytest.raises(object_storage.ObjectStorageNotConfigured):
        object_storage.upload_bytes("some/key", b"data", "text/plain")


def test_upload_then_download_roundtrips(s3_configured):
    object_storage.upload_bytes("projects/prj_1/doc1.txt", b"hello world", "text/plain")
    result = object_storage.download_bytes("projects/prj_1/doc1.txt")
    assert result == b"hello world"


def test_delete_removes_the_object(s3_configured):
    object_storage.upload_bytes("projects/prj_1/doc1.txt", b"hello", "text/plain")
    object_storage.delete_object("projects/prj_1/doc1.txt")
    with pytest.raises(object_storage.ObjectStorageError):
        object_storage.download_bytes("projects/prj_1/doc1.txt")


def test_download_nonexistent_key_raises_object_storage_error(s3_configured):
    with pytest.raises(object_storage.ObjectStorageError):
        object_storage.download_bytes("projects/prj_1/does_not_exist.txt")


def test_make_storage_key_is_namespaced_by_session_and_disambiguated_by_document_id():
    key1 = object_storage.make_storage_key("prj_alpha", "doc1", "spec.pdf")
    key2 = object_storage.make_storage_key("prj_beta", "doc2", "spec.pdf")
    assert key1 != key2
    assert "prj_alpha" in key1
    assert "prj_beta" in key2


def test_make_storage_key_sanitizes_path_separators_in_filename():
    key = object_storage.make_storage_key("prj_1", "doc1", "../../etc/passwd")
    # A path-traversal-style filename must not introduce extra "/" segments
    # into the key - exactly the 2 separators from "projects/{session}/{rest}"
    # should remain, regardless of what was in the original filename.
    assert key.count("/") == 2
    assert key.startswith("projects/prj_1/doc1_")
