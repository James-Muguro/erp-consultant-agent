"""
Authentication dependencies.

Every authenticated endpoint in the application resolves its user via
get_current_user, so this module is the single security boundary for
per-request identity.

Design notes:

  * 401 responses include a `WWW-Authenticate: Bearer` header per
    RFC 6750 §3. Standards-compliant clients and API gateways rely on
    this to know that Bearer tokens are the expected scheme (and, for
    some SDKs, to trigger token refresh).

  * decode_access_token is wrapped in try/except. A JWT library can
    raise (ExpiredSignatureError, InvalidTokenError, etc.) rather than
    returning None; without the wrapper, a malformed token produced a
    500 rather than a 401, which is both wrong (it's a client error)
    and a way for unauthenticated callers to trigger 5xx alerts.

  * The caller's user_id is bound to structlog's contextvars on
    successful resolution, so every log line emitted later in the
    request is automatically greppable by user.

  * The scheme returns None rather than raising on a missing header
    (auto_error=False), so we can shape the 401 response ourselves and
    keep it consistent with the application's error envelope.
"""
from __future__ import annotations

from src.utils.logger import get_logger
from typing import Generator, Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from src.auth.security import decode_access_token
from src.auth.service import get_user_by_id
from src.db.base import SessionLocal
from src.db.models import User
from src.utils.logger import bind_log_context

logger = get_logger(__name__)

# Scheme with auto_error=False: a missing/malformed Authorization header
# returns None here rather than raising FastAPI's default 403, letting us
# return a uniform 401 with the correct WWW-Authenticate challenge.
_bearer_scheme = HTTPBearer(auto_error=False)

# Single WWW-Authenticate value used for every 401 we raise. RFC 6750 §3.
_WWW_AUTHENTICATE_BEARER = "Bearer"

# Uniform error detail for every token-rejection case. Deliberately does
# not distinguish "expired" from "unknown user" — that distinction would
# tell an attacker whether a given user ID exists.
_UNAUTHORIZED_DETAIL = "Invalid or expired token"


def _unauthorized(detail: str = _UNAUTHORIZED_DETAIL) -> HTTPException:
    """Build a 401 with the Bearer challenge header attached."""
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": _WWW_AUTHENTICATE_BEARER},
    )


def get_db() -> Generator[Session, None, None]:
    """Yield a DB session, rolling back on exception and closing in all
    paths. Session.close() implies a rollback anyway, but being explicit
    makes the failure semantics unambiguous and matches the conventional
    FastAPI generator pattern."""
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Resolve the authenticated user from an `Authorization: Bearer <token>`
    header.

    Raises 401 for every failure mode - missing header, malformed/expired
    token, or a token whose subject no longer exists. The response never
    reveals which case occurred, so a stale token cannot be used to probe
    user-ID validity.
    """
    if credentials is None or not credentials.credentials:
        raise _unauthorized("Not authenticated")

    # Wrap decode: many JWT libraries raise on expiry or malformation
    # rather than returning a falsy value. Without this, an expired
    # token would produce a 500 instead of a 401.
    try:
        user_id = decode_access_token(credentials.credentials)
    except Exception as e:  # noqa: BLE001 - any decode failure is a 401
        # Log the failure class but not the token - a leaked token in a
        # log line is a bigger problem than a slightly-less-helpful log.
        logger.info(
            "Access token rejected",
            reason=type(e).__name__,
        )
        raise _unauthorized()

    if not user_id or not isinstance(user_id, str):
        # Defensive: a JWT `sub` claim that isn't a non-empty string is
        # not something this API ever issues. Treat it as invalid rather
        # than risking an ORM query against an unexpected type.
        raise _unauthorized()

    user = get_user_by_id(db, user_id)
    if user is None:
        # Token is valid but its subject no longer exists (user deleted).
        # Same error as an invalid token, same absence of signal.
        logger.info("Access token subject no longer exists")
        raise _unauthorized()

    # Bind for the rest of the request so subsequent log lines carry the
    # caller's identity. Wrapped in try/except because a logging setup
    # failure must not fail authentication.
    try:
        bind_log_context(user_id=user.id)
    except Exception:  # noqa: BLE001
        pass

    return user