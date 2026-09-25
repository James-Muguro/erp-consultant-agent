"""
Authentication dependencies.

Every authenticated endpoint in the application resolves its user via
get_current_user, so this module is the single security boundary for
per-request identity.

Design notes:

  * 401 responses include a `WWW-Authenticate: Bearer` header per
    RFC 6750 §3.

  * decode_access_token is wrapped in try/except. A JWT library can
    raise (ExpiredSignatureError, InvalidTokenError, etc.) rather than
    returning None; without the wrapper, a malformed token produced a
    500 rather than a 401.

  * The caller's user_id is bound to structlog's contextvars on
    successful resolution, so every log line emitted later in the
    request is automatically greppable by user.

  * The scheme returns None rather than raising on a missing header
    (auto_error=False), so we can shape the 401 response ourselves and
    keep it consistent with the application's error envelope.

CSRF (double-submit cookie)
---------------------------
State-changing requests that authenticate via the refresh cookie must
also prove they came from the SPA. The mechanism is the standard
double-submit cookie: the server issues a random CSRF cookie that is
readable by JavaScript (NOT HttpOnly), and the client must echo the
same value in a header on every cookie-authenticated request. An
attacker on another origin cannot read the CSRF cookie, so cannot
produce the matching header.

The CSRF value is NOT a credential. Possessing it does not grant
access to any resource. It proves only "the request was made by script
running on our origin."

`verify_csrf` is a plain function rather than a FastAPI dependency so
callers can control the order of checks — specifically, so a route can
return 401 "no session" when the refresh cookie is absent, and only
enforce the CSRF check once a session is actually being claimed.
"""
from __future__ import annotations

import secrets
from typing import Generator, Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from src.auth.security import decode_access_token
from src.auth.service import get_user_by_id
from src.config.settings import settings
from src.db.base import SessionLocal
from src.db.models import User
from src.utils.logger import bind_log_context, get_logger

logger = get_logger(__name__)

# Scheme with auto_error=False: a missing/malformed Authorization header
# returns None here rather than raising FastAPI's default 403, letting us
# return a uniform 401 with the correct WWW-Authenticate challenge.
_bearer_scheme = HTTPBearer(auto_error=False)

# Single WWW-Authenticate value used for every 401 we raise. RFC 6750 §3.
_WWW_AUTHENTICATE_BEARER = "Bearer"

# Uniform error detail for every token-rejection case. Deliberately does
# not distinguish "expired" from "unknown user".
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
    paths."""
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
    token, or a token whose subject no longer exists.

    This dependency NEVER accepts a pending-auth reference or a refresh
    token. Only JWT access tokens are decoded here; a pending-auth
    reference is an opaque string that fails JWT decoding immediately.
    """
    if credentials is None or not credentials.credentials:
        raise _unauthorized("Not authenticated")

    try:
        user_id = decode_access_token(credentials.credentials)
    except Exception as e:  # noqa: BLE001 - any decode failure is a 401
        logger.info(
            "Access token rejected",
            reason=type(e).__name__,
        )
        raise _unauthorized()

    if not user_id or not isinstance(user_id, str):
        raise _unauthorized()

    user = get_user_by_id(db, user_id)
    if user is None:
        logger.info("Access token subject no longer exists")
        raise _unauthorized()

    try:
        bind_log_context(user_id=user.id)
    except Exception:  # noqa: BLE001
        pass

    return user


# ---------------------------------------------------------------------------
# CSRF (double-submit cookie)
# ---------------------------------------------------------------------------
def generate_csrf_token() -> str:
    """Return a fresh CSRF token.

    Uses the OS-backed CSPRNG (Python's `secrets`). 32 bytes URL-safe
    = 256 bits, matching the entropy of the other opaque credentials in
    the auth surface. This value is not stored server-side; the
    double-submit pattern relies on the client echoing it, not on the
    server remembering it.
    """
    return secrets.token_urlsafe(32)


def verify_csrf(request: Request) -> None:
    """Enforce the double-submit check for a cookie-authenticated request.

    Reads the CSRF cookie and the CSRF header, both named from settings,
    and raises 403 when either is missing or they do not match. Uses
    `secrets.compare_digest` so the comparison does not leak where the
    two values first differ.

    The settings are read at call time (not module import time) so tests
    that override the cookie/header names via monkeypatch see the new
    values. In production the names are fixed at process startup.

    Called from inside route bodies (not as a dependency) so a route can
    decide the order relative to other checks — a request with no session
    cookie at all should get 401, not 403.
    """
    cookie_name = settings.auth_csrf_cookie_name
    header_name = settings.auth_csrf_header_name
    cookie_value = request.cookies.get(cookie_name)
    header_value = request.headers.get(header_name)
    if not cookie_value or not header_value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF check failed.",
        )
    if not secrets.compare_digest(str(cookie_value), str(header_value)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF check failed.",
        )