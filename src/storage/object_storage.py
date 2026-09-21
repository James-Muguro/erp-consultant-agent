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


# S3 allows object keys up to 1024 bytes. Reserve a safety margin so the
# returned key stays comfortably below that limit even when callers pass
# pathologically long components.
_MAX_KEY_BYTES = 1000

# Per-component byte caps. Their only purpose is to prevent a single
# hostile or malformed input from consuming the entire key budget and
# starving the other components. Real session/document IDs are short
# (hex UUIDs, DB IDs) and never come close to these values, so in
# practice the caps only kick in for malformed input.
_SESSION_ID_MAX_BYTES = 200
_DOCUMENT_ID_MAX_BYTES = 200


def _sanitize_key_component(value: str) -> str:
    """Normalize one component of the S3 key before assembly.

    * Any ``/`` or ``\\`` becomes ``_`` so a caller-supplied value cannot
      inject extra key separators. A value like ``"../evil"`` must not
      turn into a traversal-style prefix in the bucket.
    * Null bytes are removed entirely - S3 rejects keys containing them,
      and they must never survive into the returned key.
    * Valid Unicode is preserved byte-for-byte; only separators and null
      bytes are touched. No ASCII stripping, no transliteration.
    """
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    return value.replace("/", "_").replace("\\", "_").replace("\x00", "")


def _truncate_utf8(value: str, max_bytes: int) -> str:
    """Return ``value`` limited to at most ``max_bytes`` UTF-8 bytes.

    Truncation happens on a UTF-8 codepoint boundary so we never emit a
    partial multibyte sequence. ``max_bytes <= 0`` yields the empty
    string rather than an error, which keeps the caller's length math
    simple.
    """
    if max_bytes <= 0:
        return ""
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


def make_storage_key(session_id: str, document_id: str, filename: str) -> str:
    """Namespaced by project so a bucket browser (or a future per-project
    export/cleanup job) can reason about ownership from the key alone,
    and so two uploads with the same filename in different projects never
    collide. document_id (not the raw filename) disambiguates repeat
    uploads of the same filename within one project.

    Security and length constraints:

    * ``session_id``, ``document_id``, and ``filename`` are all sanitized
      so no component can inject additional ``/`` separators. The
      returned key always contains exactly two ``/`` characters, in the
      form ``projects/<session>/<document>``.
    * Null bytes are stripped from every component and can never appear
      in the returned key.
    * The whole key is bounded by ``_MAX_KEY_BYTES`` UTF-8 bytes. Only
      the filename is trimmed by *byte* length (not character count),
      so multibyte Unicode cannot quietly blow past the S3 key limit.
    * Valid Unicode in the filename is preserved; nothing is ASCII-
      stripped or transliterated.
    """
    safe_session = _truncate_utf8(
        _sanitize_key_component(session_id), _SESSION_ID_MAX_BYTES,
    )
    safe_document = _truncate_utf8(
        _sanitize_key_component(document_id), _DOCUMENT_ID_MAX_BYTES,
    )
    safe_filename = _sanitize_key_component(filename)

    prefix = f"projects/{safe_session}/{safe_document}_"

    # The per-component caps above guarantee the prefix is always well
    # under _MAX_KEY_BYTES, so `remaining` is positive here. The
    # filename absorbs the rest of the budget, truncated by UTF-8 byte
    # length rather than character count.
    remaining = _MAX_KEY_BYTES - len(prefix.encode("utf-8"))
    safe_filename = _truncate_utf8(safe_filename, remaining)

    return f"{prefix}{safe_filename}"


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