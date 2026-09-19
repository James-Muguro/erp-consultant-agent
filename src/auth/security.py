"""
Password hashing and JWT access-token helpers.

Passwords
---------
Hashing uses bcrypt directly (not passlib, which has had bcrypt-backend
compatibility issues and is effectively unmaintained). Bcrypt has a hard
72-byte input limit; longer passwords are truncated to that, which matches
bcrypt's own internal behavior. Two passwords sharing the first 72 bytes
hash identically - in practice, 72 bytes is a strong password, so this is
not exploitable for realistic user input. A future hardening option, if
you ever need to remove the truncation property entirely, is to pre-hash
with SHA-256, base64-encode the digest (avoiding NUL bytes), and pass the
result to bcrypt. That is a hash-format migration and would invalidate
existing hashes, so it is deliberately NOT done here.

Token scheme
------------
A single short-lived access token per login, HMAC-signed (HS256) with
JWT_SECRET_KEY. No refresh-token flow yet - once a token expires the user
logs in again. That is a deliberate scope cut, not an oversight.

Claims:
    sub   Subject - the user's id. Required, must be a non-empty string.
    exp   Expiry - required; decode rejects tokens without it.
    iat   Issued-at - set on every new token; used by future revocation
          logic ("revoke tokens issued before T").
    jti   JWT id - unique per token; enables per-token denylisting later.

The algorithm is fixed at import time and validated against a small
allowlist. It is NOT read from the token header (which would enable
the classic `alg: none` and RSA/HMAC confusion attacks). PyJWT's
`algorithms=[...]` option is what enforces this - the module never passes
`algorithms=None` or an empty list.
"""
from __future__ import annotations

from src.utils.logger import get_logger
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt

from src.config.settings import settings

logger = get_logger(__name__)

_BCRYPT_MAX_BYTES = 72
_BCRYPT_DEFAULT_ROUNDS = 12

# Known-safe signing algorithms. Deliberately does not include "none"
# (which PyJWT itself rejects unless you explicitly pass verify_signature=False),
# and does not mix families in a single deployment.
_SAFE_ALGORITHMS = frozenset({
    "HS256", "HS384", "HS512",   # HMAC + shared secret (this app's default)
    "RS256", "RS384", "RS512",   # RSA + key pair (if you migrate)
    "ES256", "ES384", "ES512",   # ECDSA + key pair
})


def _validate_algorithm_at_import() -> str:
    """Fail fast at import time on a misconfigured JWT algorithm. Without
    this, a JWT_ALGORITHM=none in .env produces an app that accepts
    unsigned tokens and only reveals the problem under adversarial load.

    Also logs a warning if the algorithm is asymmetric (RS*/ES*) while the
    configured secret looks like an HMAC secret - a common misconfiguration
    after switching schemes."""
    alg = (getattr(settings, "jwt_algorithm", None) or "").strip().upper()

    if not alg:
        raise RuntimeError(
            "settings.jwt_algorithm is empty. Set it to HS256 (default for "
            "this deployment's symmetric-secret scheme)."
        )
    if alg not in _SAFE_ALGORITHMS:
        raise RuntimeError(
            f"settings.jwt_algorithm is {alg!r}, which is not in the "
            f"allowlist {sorted(_SAFE_ALGORITHMS)}. The value 'none' is "
            "never acceptable - it disables signature verification."
        )
    if alg.startswith(("RS", "ES")):
        logger.warning(
            "JWT algorithm is asymmetric (%s). Ensure jwt_secret_key is a "
            "PEM-encoded key, not an HMAC secret.", alg,
        )
    return alg


# Resolved once at import; every call to create/decode uses this value.
_JWT_ALGORITHM = _validate_algorithm_at_import()


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------
def hash_password(
    plain_password: str,
    *,
    rounds: Optional[int] = None,
) -> str:
    """Hash a password with bcrypt.

    The `rounds` parameter is optional and intended for tests - production
    callers should leave it None to use the default cost factor (12)."""
    if not isinstance(plain_password, str):
        raise TypeError("plain_password must be a string")
    truncated = plain_password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    salt = (
        bcrypt.gensalt(rounds=rounds)
        if rounds is not None
        else bcrypt.gensalt()
    )
    return bcrypt.hashpw(truncated, salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Constant-time password verification. Returns False (never raises)
    on any malformed input - a bad hash row must not crash a login attempt
    into a 500."""
    if not isinstance(plain_password, str) or not isinstance(hashed_password, str):
        return False
    truncated = plain_password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    try:
        return bcrypt.checkpw(truncated, hashed_password.encode("utf-8"))
    except (ValueError, TypeError):
        # Malformed hash, wrong prefix, truncated base64 - all client
        # errors in practice. Do not let them become 500s.
        return False


# ---------------------------------------------------------------------------
# Access tokens
# ---------------------------------------------------------------------------
def create_access_token(
    user_id: str,
    expires_minutes: Optional[int] = None,
) -> str:
    """Issue a signed access token for `user_id`.

    Adds `iat` (issued-at) and `jti` (unique token id) alongside the
    required `sub` and `exp`. Both are additive - tokens minted before
    this change (with only `sub` and `exp`) still decode successfully
    under decode_access_token because neither claim is required on read.
    """
    if not isinstance(user_id, str) or not user_id:
        raise ValueError("user_id must be a non-empty string")

    # Use explicit None check so a caller can pass 0 deliberately.
    if expires_minutes is None:
        expires_minutes = settings.access_token_expire_minutes

    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "iat": now,
        "exp": now + timedelta(minutes=expires_minutes),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=_JWT_ALGORITHM)


def decode_access_token(token: str) -> Optional[str]:
    """Return the token's `sub` claim if the token is valid, unexpired,
    and well-formed; otherwise None. Never raises.

    Enforcement:
      - Signature must verify under `_JWT_ALGORITHM` (never read from the
        token header - PyJWT's `algorithms=[...]` allowlist prevents both
        `alg: none` and RSA/HMAC confusion).
      - `exp` must be present and unexpired.
      - `sub` must be a non-empty string; anything else is treated as an
        invalid token rather than passed downstream.
    """
    if not isinstance(token, str) or not token:
        return None

    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[_JWT_ALGORITHM],
            options={
                # Refuse tokens that omit exp even if they verify. Without
                # this, a token signed without an expiry would be valid
                # forever.
                "require": ["exp"],
                # Belt and braces: reject tokens that explicitly try to
                # opt out of signature verification via the header.
                "verify_signature": True,
            },
        )
    except jwt.PyJWTError as e:
        # Covers ExpiredSignatureError, InvalidTokenError, DecodeError,
        # ImmatureSignatureError, and every other PyJWT failure mode.
        logger.debug("JWT rejected", reason=type(e).__name__)
        return None
    except Exception as e:  # noqa: BLE001 - any decode failure is a rejection
        # Defensive: an unexpected exception from the JWT library (a
        # misconfigured secret, a version change, ...) must not
        # propagate to the caller as a 500. Log the class only; never
        # log the token itself.
        logger.warning("Unexpected JWT decode error", reason=type(e).__name__)
        return None

    sub = payload.get("sub")
    if not isinstance(sub, str) or not sub:
        # A token with a missing, empty, or non-string subject is not one
        # this API ever issues. Treat as invalid rather than risk the ORM
        # receiving an unexpected type.
        return None
    return sub