"""
Password hashing and JWT access-token helpers.

Passwords: bcrypt via the `bcrypt` package directly (not passlib, which is
effectively unmaintained and has had bcrypt-backend compatibility issues).
Bcrypt has a hard 72-byte input limit - passwords are truncated to that
before hashing, which is the standard, documented way to use it safely.

Tokens: a single short-lived access token per login, HMAC-signed (HS256)
with JWT_SECRET_KEY. No refresh-token flow yet (see settings.py) - once a
token expires the user just logs in again. That's a deliberate scope cut
for this stage, not an oversight.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt

from src.config.settings import settings

_BCRYPT_MAX_BYTES = 72


def hash_password(plain_password: str) -> str:
    truncated = plain_password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    return bcrypt.hashpw(truncated, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    truncated = plain_password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    try:
        return bcrypt.checkpw(truncated, hashed_password.encode("utf-8"))
    except ValueError:
        # Malformed hash - never let this crash a login attempt into a 500.
        return False


def create_access_token(user_id: str, expires_minutes: Optional[int] = None) -> str:
    expire_minutes = expires_minutes or settings.access_token_expire_minutes
    expire = datetime.now(timezone.utc) + timedelta(minutes=expire_minutes)
    payload = {"sub": user_id, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> Optional[str]:
    """Returns the user_id (sub claim) if the token is valid and unexpired,
    else None. Never raises - callers treat None as 401."""
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        return payload.get("sub")
    except jwt.PyJWTError:
        return None
