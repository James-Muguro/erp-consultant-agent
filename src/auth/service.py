"""
User account operations against the `users` table.

Kept as plain functions taking a SQLAlchemy Session rather than a class,
matching the lightweight style of the rest of the codebase.

Design notes on this revision:

  * authenticate_user is timing-resistant. A login attempt for a
    nonexistent email spends the same wall-clock time (bcrypt on a
    fixed dummy hash) as one for an existing email with the wrong
    password, so the response time no longer reveals whether an email
    is registered.

  * create_user handles the concurrent-signup race. Two parallel
    signups for the same email both pass the pre-check, then one hits
    the unique constraint on commit; that IntegrityError is
    translated into EmailAlreadyRegistered so the endpoint returns the
    same 409 it would for a sequential signup.

  * Every mutating function rolls back explicitly on failure. The
    get_db dependency closes sessions on exception, but explicit
    rollback makes the semantics correct for direct callers (tests,
    background jobs) too.

  * Failed authentications are logged with reason class but never the
    password or the exact distinguishing detail.
"""
from __future__ import annotations

from src.utils.logger import get_logger
import uuid
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.auth.security import hash_password, verify_password
from src.db.models import User

logger = get_logger(__name__)


class EmailAlreadyRegistered(Exception):
    """Raised when a signup targets an email that already exists.
    Endpoint translates this to HTTP 409."""


# ---------------------------------------------------------------------------
# Dummy hash for timing-resistant authentication
# ---------------------------------------------------------------------------
# Computed once at import so login attempts against unknown emails still
# spend the same bcrypt work as login attempts against known emails with a
# wrong password. The literal below is never a valid user password - it's
# thrown away after hashing, and the resulting hash is only ever passed to
# verify_password to burn the same ~250ms. Cost factors are identical to
# production hashes because both use hash_password's default rounds.
_DUMMY_HASH_FOR_TIMING = hash_password(
    "definitely-not-a-real-password-for-timing-resistance"
)


def get_user_by_email(db: Session, email: str) -> Optional[User]:
    """Primary-key-alternative lookup, lowercased on the way in so callers
    can't accidentally bypass the normalization done at signup."""
    return db.query(User).filter(User.email == email.lower()).first()


def get_user_by_id(db: Session, user_id: str) -> Optional[User]:
    """Primary-key lookup (uses Session.get, which is the fast path)."""
    return db.get(User, user_id)


def create_user(db: Session, email: str, password: str) -> User:
    """Create a user account.

    Raises EmailAlreadyRegistered if the email is already in use. Handles
    the concurrent-signup case where two requests pass the pre-check
    simultaneously and one hits the unique constraint on commit.
    """
    email = email.lower()

    # Cheap pre-check so we can return a fast, clean error in the common
    # case. Not sufficient on its own - see the IntegrityError handler
    # below, which catches the race.
    if get_user_by_email(db, email):
        raise EmailAlreadyRegistered(f"{email} is already registered")

    # Hash BEFORE the try block: hash_password doesn't touch the DB, and
    # keeping it outside means a hashing failure can't leave a pending
    # transaction behind.
    hashed = hash_password(password)

    user = User(
        id=uuid.uuid4().hex,
        email=email,
        hashed_password=hashed,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as e:
        # Concurrent signup won the race. The unique constraint on
        # users.email is what fired; translate it into the same error the
        # sequential path returns, so the endpoint's HTTP status is
        # consistent regardless of timing.
        db.rollback()
        logger.info("Signup raced on email unique constraint", email_lower=email)
        raise EmailAlreadyRegistered(f"{email} is already registered") from e
    except Exception:
        # Any other commit failure (DB down, disk full) - roll back so
        # the session isn't left with a pending transaction, then
        # propagate. This is a server-side error, not a client error.
        db.rollback()
        raise

    db.refresh(user)
    return user


def authenticate_user(db: Session, email: str, password: str) -> Optional[User]:
    """Verify credentials.

    Timing-resistant: a login against a nonexistent email spends the same
    bcrypt work as a login against an existing email with a wrong
    password, so response time doesn't leak whether an email is
    registered. Returns None on any failure (unknown email, wrong
    password, malformed stored hash) - the endpoint turns that into a
    uniform 401.
    """
    user = get_user_by_email(db, email)

    if user is None:
        # Burn the same amount of time a real verify would. The return
        # value is discarded - we only care that bcrypt ran.
        verify_password(password, _DUMMY_HASH_FOR_TIMING)
        logger.info("Authentication failed", reason="unknown_email")
        return None

    if not verify_password(password, user.hashed_password):
        logger.info("Authentication failed", reason="bad_password", user_id=user.id)
        return None

    return user


def update_profile(
    db: Session,
    user: User,
    name: Optional[str],
    profile_picture_url: Optional[str],
) -> User:
    """Update display name and/or profile picture URL.

    Semantics note: this is a full-replace for both fields - a caller
    passing None for a field clears it. That matches the current endpoint's
    behavior (which passes the current value for the field it isn't
    changing). If partial-update semantics are ever needed, add a sentinel
    to distinguish "not provided" from "explicitly cleared".

    Whitespace-only name is treated as None (clears the field), which
    matches the schema's stripping validator for the same reason.
    """
    user.name = name.strip() if name and name.strip() else None
    user.profile_picture_url = (
        profile_picture_url.strip() if profile_picture_url and profile_picture_url.strip() else None
    )

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(user)
    return user


def change_password(
    db: Session,
    user: User,
    current_password: str,
    new_password: str,
) -> bool:
    """Change a user's password.

    Returns True on success, False if the current password is wrong.

    NOTE: this does not invalidate existing access tokens. Tokens issued
    before the password change remain valid until their `exp` (up to
    `settings.access_token_expire_minutes`, default 24h). If an account
    was compromised, the attacker's token survives the password change.
    Closing this requires either (a) a token denylist keyed on the user's
    `jti` claims issued before the change, or (b) a per-user
    `password_changed_at` timestamp that get_current_user compares
    against the token's `iat`. Both are architectural changes; flagging
    rather than implementing.

    Also does not enforce password history or a "recently authenticated"
    requirement. See src/auth/schemas.py for the creation-time policy.
    """
    if not verify_password(current_password, user.hashed_password):
        logger.info("Password change rejected", reason="bad_current_password", user_id=user.id)
        return False

    user.hashed_password = hash_password(new_password)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    logger.info("Password changed", user_id=user.id)
    return True