"""
S3-compatible object storage client for uploaded project documents.

Works with AWS S3, Cloudflare R2, MinIO, or any S3-compatible provider -
provider choice is just which env vars you set (S3_ENDPOINT_URL for
R2/MinIO, unset for real AWS S3). Documents live here, never on local
disk or in the app's own database - Render's disk is ephemeral, and
consultant-uploaded files (unlike the smaller AI-generated documents in
GeneratedDocument) can be large enough that a bytea column is the wrong
tool.
"""
import boto3
from botocore.exceptions import ClientError
from typing import Optional

from src.config.settings import settings
from src.utils.logger import get_logger

logger = get_logger(__name__)


class ObjectStorageNotConfigured(Exception):
    """Raised when an upload/download is attempted before S3 credentials
    are set - callers turn this into a 503 with a clear message, not a
    500 or a confusing boto3 traceback."""
    pass


class ObjectStorageError(Exception):
    """Wraps a lower-level boto3/ClientError failure (network issue, wrong
    credentials, bucket doesn't exist, etc.) into one clear type callers
    can catch without depending on botocore's exception hierarchy."""
    pass


def _get_client():
    if not settings.object_storage_configured:
        raise ObjectStorageNotConfigured(
            "Object storage isn't configured (S3_BUCKET_NAME / S3_ACCESS_KEY_ID / "
            "S3_SECRET_ACCESS_KEY). File upload is unavailable until these are set."
        )
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key_id,
        aws_secret_access_key=settings.s3_secret_access_key,
        region_name=settings.s3_region,
    )


def make_storage_key(session_id: str, document_id: str, filename: str) -> str:
    """Namespaced by project so a bucket browser (or a future per-project
    export/cleanup job) can reason about ownership from the key alone,
    and so two uploads with the same filename in different projects never
    collide. document_id (not the raw filename) disambiguates repeat
    uploads of the same filename within one project."""
    safe_filename = filename.replace("/", "_").replace("\\", "_")
    return f"projects/{session_id}/{document_id}_{safe_filename}"


def upload_bytes(key: str, data: bytes, content_type: str) -> None:
    client = _get_client()
    try:
        client.put_object(
            Bucket=settings.s3_bucket_name, Key=key, Body=data, ContentType=content_type
        )
    except ClientError as e:
        logger.error("Object storage upload failed", key=key, error=str(e))
        raise ObjectStorageError(f"Upload failed: {e}") from e


def download_bytes(key: str) -> bytes:
    client = _get_client()
    try:
        response = client.get_object(Bucket=settings.s3_bucket_name, Key=key)
        return response["Body"].read()
    except ClientError as e:
        logger.error("Object storage download failed", key=key, error=str(e))
        raise ObjectStorageError(f"Download failed: {e}") from e


def delete_object(key: str) -> None:
    client = _get_client()
    try:
        client.delete_object(Bucket=settings.s3_bucket_name, Key=key)
    except ClientError as e:
        logger.error("Object storage delete failed", key=key, error=str(e))
        raise ObjectStorageError(f"Delete failed: {e}") from e
