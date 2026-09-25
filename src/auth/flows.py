"""
Authentication flow layer.

This module composes the primitives provided by lower layers into the
complete set of user-facing authentication flows:

    - Signup (five account types) + email verification + resend
    - Login via password + email-OTP MFA (with pending-auth state)
    - Refresh-token rotation with reuse detection and family revocation
    - Logout and logout-all-devices
    - Forgot password + password reset completion
    - Progressive failed-login and failed-OTP abuse controls
    - Audit event emission

It does NOT define new security primitives. Password hashing,
verification, JWT issuance/decoding, secure token generation, OTP
generation, and constant-time comparison all come from
`src.auth.security`. User CRUD (create_user, get_user_by_email,
authenticate_user, update_profile, change_password) comes from
`src.auth.service`. Email delivery comes from `src.email.send_email`.
The concrete Gmail SMTP transport is never imported here.

Transaction boundaries
----------------------
Every write path commits before returning. Email is sent AFTER commit so
that a delivery failure never rolls back a successful state change (a
failed email can be retried via the resend flow without touching the DB
state). Audit rows are written in the SAME transaction as the state
change they describe, so an audit event can never disagree with what
actually happened.

Concurrency
-----------
Three flows serialize on a row lock (`SELECT ... FOR UPDATE`) to prevent
double-consumption under concurrent requests:

    - OTP verification        (locks the AuthOtpRecord row)
    - Refresh-token rotation  (locks the AuthRefreshToken row by hash)
    - Failed-login increments (locks the User row)

`FOR UPDATE` is a no-op on SQLite (which serializes writers at the
database level) and the intended behavior on PostgreSQL. Both engines
satisfy the "no two winners" invariant.

Enumeration resistance
----------------------
Existence-sensitive outcomes use a single generic exception:

    LoginFailed           - unknown email, wrong password, locked account
    OtpVerificationFailed - unknown ref, wrong code, expired, used, locked
    SessionExpired        - unknown/revoked/expired/reused refresh token

The route layer MUST return the same response for every case within each
class. Signup with a duplicate email and password-reset requests return a
normal-shaped outcome and never raise on the existence check.
Client-checkable validation errors (password length, email format, OTP
format) remain specific.

Never logged
------------
Passwords, raw access tokens, raw refresh tokens, raw reset tokens, raw
verification tokens, raw OTP codes, SMTP credentials. The audit table and
the application log both respect this.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from src.auth import service as user_service
from src.auth.security import (
    constant_time_equal,
    create_access_token,
    generate_otp,
    generate_secure_token,
    hash_password,
    hash_token,
    verify_password,
)
from src.config.settings import settings
from src.db.models import (
    AuthAuditEvent,
    AuthEmailVerificationToken,
    AuthOtpRecord,
    AuthPasswordResetToken,
    AuthRefreshToken,
    User,
)
from src.email import EmailError, send_email
from src.utils.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------
class AuthError(Exception):
    """Base class for every error raised by this module."""


class LoginFailed(AuthError):
    """Raised for every failed login attempt: unknown email, wrong
    password, or a locked account. Routes MUST return the same generic
    response for all three so account existence is not revealed."""


class OtpVerificationFailed(AuthError):
    """Raised for every failed OTP verification: unknown ref, wrong code,
    expired, used, or attempt limit reached. Routes MUST return the same
    generic response for all of these."""


class SessionExpired(AuthError):
    """Raised when a refresh token is invalid, expired, revoked, or
    reused. Routes MUST return a generic 401 and clear the refresh
    cookie. Do not distinguish reuse from expiry to the client."""


class InvalidOrExpiredToken(AuthError):
    """Raised when an email-verification or password-reset token is
    malformed, unknown, expired, or already used. The token is presented
    by the user (not derived from an email address) so a specific error
    does not reveal account existence."""


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class SignupOutcome:
    """Result of a signup attempt.

    `user_id` is None when the email was already registered. The route
    MUST NOT distinguish the two cases in its response (enumeration
    resistance).
    """
    user_id: Optional[str]


@dataclass(frozen=True)
class PendingLogin:
    """Result of a successful password verification in the login flow.

    `pending_auth_ref` is the reference the client submits alongside the
    OTP code. It cannot be used as an access token or a refresh token,
    and it is single-use (invalidated after successful verification) and
    short-lived (bounded by settings.pending_auth_expire_minutes)."""
    pending_auth_ref: str
    expires_in_minutes: int


@dataclass(frozen=True)
class IssuedTokens:
    """Successful authentication. The refresh_token is the raw value the
    caller must deliver via a Secure HttpOnly cookie; it is never stored
    or returned anywhere else."""
    access_token: str
    refresh_token: str
    access_expires_in_minutes: int
    refresh_expires_in_days: int


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_OTP_PURPOSE_LOGIN_MFA = "login_mfa"

# Generic responses surfaced through the exception classes above. Kept
# here so tests can assert on the exact wording and so the routes do not
# have to re-invent it.
_GENERIC_LOGIN_ERROR = "Invalid email or password."
_GENERIC_OTP_ERROR = "Invalid or expired code."
_GENERIC_TOKEN_ERROR = "This link is invalid or has expired."

# Bounds for user-agent and IP columns (models declare them as unbounded
# String; truncating keeps a hostile client from filling a row with a
# multi-megabyte value).
_USER_AGENT_MAX = 512
_IP_MAX = 64


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
    """Coerce a DB datetime to timezone-aware UTC.

    PostgreSQL returns aware datetimes for `DateTime(timezone=True)`
    columns; SQLite may return naive ones. Comparisons must be against a
    single representation or a stale row can appear future-dated.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _truncate(value: Optional[str], limit: int) -> Optional[str]:
    if value is None:
        return None
    text = str(value)
    if not text:
        return None
    return text[:limit]


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------
def _record_audit(
    db: Session,
    *,
    event_type: str,
    outcome: str,
    user_id: Optional[str] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Add an audit row to the current transaction. The caller commits.

    Never pass secrets through `metadata`. The audit trail is designed to
    outlive accounts (user_id FK is ON DELETE SET NULL) and is assumed to
    be readable by anyone with operational access.
    """
    db.add(AuthAuditEvent(
        id=uuid.uuid4().hex,
        user_id=user_id,
        event_type=event_type,
        outcome=outcome,
        ip_address=_truncate(ip_address, _IP_MAX),
        user_agent=_truncate(user_agent, _USER_AGENT_MAX),
        event_metadata=metadata,
    ))


# ---------------------------------------------------------------------------
# Email content and delivery
# ---------------------------------------------------------------------------
def _frontend_base_url() -> str:
    """Base URL used to build user-facing links in emails.

    Uses the first entry in `settings.allowed_origins_list` as the
    canonical frontend origin - in a standard deployment the SPA is
    served from one of the configured trusted origins, and the first is
    the primary one. Documented as an assumption: if the frontend ever
    runs on a different host than the API's trusted origins, add a
    dedicated `frontend_base_url` setting rather than silently changing
    this.
    """
    origins = settings.allowed_origins_list
    return origins[0] if origins else "http://localhost:3000"


def _send_email_safe(
    to: str,
    subject: str,
    body: str,
    *,
    context: str,
) -> bool:
    """Send an email, logging a warning on failure but never raising.

    Auth flows must not fail because the email provider is unavailable -
    a signup whose verification email could not be delivered is still a
    valid signup (the user can request a resend); a login whose OTP email
    could not be delivered still has a valid pending-auth row (the user
    can trigger a resend after the throttle interval).

    Returns True on success, False otherwise. The failure is logged with
    a short context tag and the failure class; never the body, the
    recipient address, or any credential.
    """
    try:
        send_email(to, subject, body)
        return True
    except EmailError as e:
        logger.warning(
            "Auth email delivery failed",
            context=context,
            failure_class=type(e).__name__,
        )
        return False
    except Exception as e:  # noqa: BLE001 - defensive, must not fail the flow
        logger.warning(
            "Auth email delivery failed (unexpected)",
            context=context,
            failure_class=type(e).__name__,
        )
        return False


def _verification_email_body(user: User, raw_token: str) -> str:
    link = f"{_frontend_base_url()}/verify-email?token={raw_token}"
    hours = settings.email_verification_expire_hours
    name = user.name or "there"
    return (
        f"Hi {name},\n\n"
        "Confirm this email address to finish setting up your account:\n\n"
        f"{link}\n\n"
        f"This link expires in {hours} hour(s).\n\n"
        "If you didn't create this account, you can safely ignore this email.\n"
    )


def _password_reset_email_body(user: User, raw_token: str) -> str:
    link = f"{_frontend_base_url()}/reset-password?token={raw_token}"
    minutes = settings.password_reset_expire_minutes
    name = user.name or "there"
    return (
        f"Hi {name},\n\n"
        "We received a request to reset the password for your account.\n\n"
        f"{link}\n\n"
        f"This link expires in {minutes} minute(s).\n\n"
        "If you didn't request a password reset, you can safely ignore this "
        "email. Your password will remain unchanged.\n"
    )


def _otp_email_body(code: str) -> str:
    minutes = settings.otp_expire_minutes
    return (
        "Your sign-in code is:\n\n"
        f"    {code}\n\n"
        f"This code expires in {minutes} minute(s).\n\n"
        "If you didn't try to sign in, change your password immediately.\n"
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _is_locked(user: User) -> bool:
    locked_until = _as_utc(user.locked_until)
    if locked_until is None:
        return False
    return locked_until > _utcnow()


def _reset_login_failures(user: User) -> None:
    user.failed_login_count = 0
    user.locked_until = None


def _increment_login_failures(db: Session, user_id: str) -> bool:
    """Increment the failed-login counter with a row lock, and lock the
    account if the threshold is reached. Returns True if the account
    became locked on this call. Caller commits.

    The `FOR UPDATE` re-query serializes concurrent failures so two
    requests racing on the same account cannot each read the same
    pre-increment count.
    """
    row = (
        db.query(User)
        .filter(User.id == user_id)
        .with_for_update()
        .first()
    )
    if row is None:
        return False
    row.failed_login_count = (row.failed_login_count or 0) + 1
    if row.failed_login_count >= settings.login_max_failed_attempts:
        if not _is_locked(row):
            row.locked_until = _utcnow() + timedelta(
                minutes=settings.login_lockout_duration_minutes
            )
            return True
    return False


def _issue_refresh_token(
    db: Session,
    *,
    user_id: str,
    family_id: Optional[str] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> str:
    """Create a new AuthRefreshToken row. Returns the RAW token - the
    caller delivers it to the client and never stores it anywhere else.
    Only the SHA-256 digest is written to the database."""
    raw = generate_secure_token()
    row = AuthRefreshToken(
        id=uuid.uuid4().hex,
        user_id=user_id,
        family_id=family_id or uuid.uuid4().hex,
        token_hash=hash_token(raw),
        expires_at=_utcnow() + timedelta(days=settings.refresh_token_expire_days),
        ip_address=_truncate(ip_address, _IP_MAX),
        user_agent=_truncate(user_agent, _USER_AGENT_MAX),
    )
    db.add(row)
    return raw


def _find_pending_otp(db: Session, user_id: str) -> Optional[AuthOtpRecord]:
    """Most recent unconsumed OTP for the user's login_mfa flow, or None."""
    return (
        db.query(AuthOtpRecord)
        .filter(
            AuthOtpRecord.user_id == user_id,
            AuthOtpRecord.purpose == _OTP_PURPOSE_LOGIN_MFA,
            AuthOtpRecord.used_at.is_(None),
        )
        .order_by(AuthOtpRecord.created_at.desc())
        .first()
    )


# ---------------------------------------------------------------------------
# Signup
# ---------------------------------------------------------------------------
def signup(
    db: Session,
    *,
    email: str,
    password: str,
    account_type,
    organization_name: Optional[str] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> SignupOutcome:
    """Create a new account and send a verification email.

    Account types and their role/tenant effects are handled by
    `src.auth.service.create_user` (the single-transaction primitive):
    individual types grant the matching application role; the
    'organization' type creates the tenant and an Owner membership and
    grants NO application role.

    The user is created with `email_verified_at = NULL`; verification is
    completed separately. No access or refresh tokens are issued here -
    the client must go through the login flow (password + OTP) to obtain
    credentials.

    Enumeration resistance: when the email is already registered the
    outcome has `user_id=None`, no verification email is sent, and a
    bcrypt hash is burned so timing matches the success path.
    """
    try:
        user = user_service.create_user(
            db,
            email,
            password,
            account_type=account_type,
            organization_name=organization_name,
        )
    except user_service.EmailAlreadyRegistered:
        # Burn the bcrypt work that the success path performs, so the
        # duplicate-email response is not measurably faster.
        try:
            hash_password(password)
        except Exception:  # noqa: BLE001
            pass
        _record_audit(
            db,
            event_type="signup_rejected",
            outcome="failure",
            ip_address=ip_address,
            user_agent=user_agent,
            metadata={"reason": "email_already_registered"},
        )
        db.commit()
        return SignupOutcome(user_id=None)

    # create_user committed; the user exists in an unverified state.
    raw_token = generate_secure_token()
    now = _utcnow()
    db.add(AuthEmailVerificationToken(
        id=uuid.uuid4().hex,
        user_id=user.id,
        token_hash=hash_token(raw_token),
        expires_at=now + timedelta(hours=settings.email_verification_expire_hours),
    ))
    _record_audit(
        db,
        event_type="signup_completed",
        outcome="success",
        user_id=user.id,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    _record_audit(
        db,
        event_type="email_verification_requested",
        outcome="success",
        user_id=user.id,
        ip_address=ip_address,
        user_agent=user_agent,
        metadata={"source": "signup"},
    )
    db.commit()

    _send_email_safe(
        user.email,
        "Verify your email address",
        _verification_email_body(user, raw_token),
        context="signup_verification",
    )
    return SignupOutcome(user_id=user.id)


# ---------------------------------------------------------------------------
# Email verification
# ---------------------------------------------------------------------------
def verify_email(
    db: Session,
    *,
    raw_token: str,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> User:
    """Complete email verification with the raw token from the link.

    Single-use: the token row is marked used_at on success and cannot be
    replayed. Expired or already-used tokens raise InvalidOrExpiredToken
    with the same generic message (the token itself is presented by the
    user, so specificity here does not reveal account existence).
    """
    token_hash = hash_token(raw_token)
    row = (
        db.query(AuthEmailVerificationToken)
        .filter(AuthEmailVerificationToken.token_hash == token_hash)
        .with_for_update()
        .first()
    )

    if row is None or row.used_at is not None:
        _record_audit(
            db,
            event_type="email_verification_failed",
            outcome="failure",
            ip_address=ip_address,
            user_agent=user_agent,
            metadata={"reason": "invalid_or_used"},
        )
        db.commit()
        raise InvalidOrExpiredToken(_GENERIC_TOKEN_ERROR)

    now = _utcnow()
    if _as_utc(row.expires_at) <= now:
        row.used_at = now
        _record_audit(
            db,
            event_type="email_verification_failed",
            outcome="failure",
            user_id=row.user_id,
            ip_address=ip_address,
            user_agent=user_agent,
            metadata={"reason": "expired"},
        )
        db.commit()
        raise InvalidOrExpiredToken(_GENERIC_TOKEN_ERROR)

    user = db.get(User, row.user_id)
    if user is None:
        row.used_at = now
        db.commit()
        raise InvalidOrExpiredToken(_GENERIC_TOKEN_ERROR)

    row.used_at = now
    if user.email_verified_at is None:
        user.email_verified_at = now

    _record_audit(
        db,
        event_type="email_verification_succeeded",
        outcome="success",
        user_id=user.id,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.commit()
    return user


def resend_verification_email(
    db: Session,
    *,
    email: str,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> None:
    """Send a fresh verification email.

    Enumeration-resistant: always returns normally. No email is sent for
    an unknown address, for an already-verified account, or within the
    configured resend interval.

    Supersedes any prior unused token for the same user by marking it
    used_at, so only the newest link works.
    """
    user = user_service.get_user_by_email(db, email)

    if user is None:
        _record_audit(
            db,
            event_type="email_verification_requested",
            outcome="failure",
            ip_address=ip_address,
            user_agent=user_agent,
            metadata={"reason": "unknown_email", "source": "resend"},
        )
        db.commit()
        return

    if user.email_verified_at is not None:
        _record_audit(
            db,
            event_type="email_verification_requested",
            outcome="failure",
            user_id=user.id,
            ip_address=ip_address,
            user_agent=user_agent,
            metadata={"reason": "already_verified", "source": "resend"},
        )
        db.commit()
        return

    # Throttle: reuse the configured auth resend interval. The most
    # recent verification token's created_at is the anchor.
    now = _utcnow()
    latest = (
        db.query(AuthEmailVerificationToken)
        .filter(AuthEmailVerificationToken.user_id == user.id)
        .order_by(AuthEmailVerificationToken.created_at.desc())
        .first()
    )
    if latest is not None:
        age = (now - _as_utc(latest.created_at)).total_seconds()
        if age < settings.otp_resend_interval_seconds:
            _record_audit(
                db,
                event_type="email_verification_requested",
                outcome="failure",
                user_id=user.id,
                ip_address=ip_address,
                user_agent=user_agent,
                metadata={"reason": "throttled", "source": "resend"},
            )
            db.commit()
            return

    # Supersede prior unused tokens.
    db.query(AuthEmailVerificationToken).filter(
        AuthEmailVerificationToken.user_id == user.id,
        AuthEmailVerificationToken.used_at.is_(None),
    ).update({"used_at": now}, synchronize_session=False)

    raw_token = generate_secure_token()
    db.add(AuthEmailVerificationToken(
        id=uuid.uuid4().hex,
        user_id=user.id,
        token_hash=hash_token(raw_token),
        expires_at=now + timedelta(hours=settings.email_verification_expire_hours),
    ))
    _record_audit(
        db,
        event_type="email_verification_requested",
        outcome="success",
        user_id=user.id,
        ip_address=ip_address,
        user_agent=user_agent,
        metadata={"source": "resend"},
    )
    db.commit()

    _send_email_safe(
        user.email,
        "Verify your email address",
        _verification_email_body(user, raw_token),
        context="resend_verification",
    )


# ---------------------------------------------------------------------------
# Login — password verification
# ---------------------------------------------------------------------------
def initiate_login(
    db: Session,
    *,
    email: str,
    password: str,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> PendingLogin:
    """Stage 1 of login: verify the password and issue an MFA challenge.

    The lock state is checked BEFORE password verification, but the
    response is identical to a wrong-password response so the lock state
    is not exposed. Every failure path burns the same bcrypt work as a
    normal verification.

    On success: the failed-login counters are reset, an OTP is generated
    and sent, and the opaque `pending_auth_ref` is returned. The ref
    cannot be used as an access token and is invalidated the moment the
    OTP is either verified or invalidated (by attempt limit, expiry, or
    a subsequent login that supersedes it).
    """
    user = user_service.get_user_by_email(db, email)

    # 1. Locked account: burn bcrypt time, audit, generic failure.
    if user is not None and _is_locked(user):
        verify_password(password, user.hashed_password)
        _record_audit(
            db,
            event_type="login_failed",
            outcome="failure",
            user_id=user.id,
            ip_address=ip_address,
            user_agent=user_agent,
            metadata={"reason": "account_locked"},
        )
        db.commit()
        raise LoginFailed(_GENERIC_LOGIN_ERROR)

    # 2. Password verification. `authenticate_user` is timing-resistant:
    #    unknown emails burn a dummy bcrypt comparison.
    authenticated = user_service.authenticate_user(db, email, password)

    if authenticated is None:
        if user is not None:
            newly_locked = _increment_login_failures(db, user.id)
            _record_audit(
                db,
                event_type="login_failed",
                outcome="failure",
                user_id=user.id,
                ip_address=ip_address,
                user_agent=user_agent,
                metadata={"reason": "bad_password"},
            )
            if newly_locked:
                _record_audit(
                    db,
                    event_type="account_locked",
                    outcome="success",
                    user_id=user.id,
                    ip_address=ip_address,
                    user_agent=user_agent,
                    metadata={
                        "threshold": settings.login_max_failed_attempts,
                        "lockout_minutes": settings.login_lockout_duration_minutes,
                    },
                )
        else:
            _record_audit(
                db,
                event_type="login_failed",
                outcome="failure",
                ip_address=ip_address,
                user_agent=user_agent,
                metadata={"reason": "unknown_email"},
            )
        db.commit()
        raise LoginFailed(_GENERIC_LOGIN_ERROR)

    # 3. Success: reset progressive counters.
    _reset_login_failures(authenticated)

    # 4. OTP issuance with throttle.
    #
    # Invariant: at most ONE unconsumed login_mfa OTP exists per user at
    # any time. Superseding prior OTPs is what prevents an attacker who
    # knows the password from accumulating multiple concurrently-valid
    # OTPs — each with its own attempt budget — and thereby multiplying
    # the permitted guess count. The supersession and the new row insert
    # happen in the same transaction, under a row lock on the user, so
    # two concurrent logins for the same account cannot both leave a
    # live OTP behind.
    #
    # Lock the user row so the decision is serialized. This mirrors the
    # pattern used by _increment_login_failures on the failure path.
    db.query(User).filter(User.id == authenticated.id).with_for_update().first()

    now = _utcnow()
    existing = _find_pending_otp(db, authenticated.id)

    if existing is not None:
        existing_expires = _as_utc(existing.expires_at)
        existing_created = _as_utc(existing.created_at)
        within_interval = (
            (now - existing_created).total_seconds()
            < settings.otp_resend_interval_seconds
        )
        if existing_expires is not None and existing_expires > now and within_interval:
            # Throttled: reuse the existing ref, no new email.
            _record_audit(
                db,
                event_type="otp_requested",
                outcome="success",
                user_id=authenticated.id,
                ip_address=ip_address,
                user_agent=user_agent,
                metadata={"purpose": _OTP_PURPOSE_LOGIN_MFA, "throttled": True},
            )
            db.commit()
            return PendingLogin(
                pending_auth_ref=existing.id,
                expires_in_minutes=settings.otp_expire_minutes,
            )

    # Supersede every prior unconsumed login_mfa OTP for this user. This
    # is the enforcement point for the "one active OTP per user"
    # invariant. It runs on every path that reaches the OTP-creation
    # branch, including the "existing OTP is expired" path — the previous
    # implementation only marked the expired one used and left any
    # still-valid sibling unconsumed, allowing accumulation.
    superseded = (
        db.query(AuthOtpRecord)
        .filter(
            AuthOtpRecord.user_id == authenticated.id,
            AuthOtpRecord.purpose == _OTP_PURPOSE_LOGIN_MFA,
            AuthOtpRecord.used_at.is_(None),
        )
        .update({"used_at": now}, synchronize_session=False)
    )
    if superseded:
        logger.info(
            "Superseded prior login OTPs before issuing a new one",
            user_id=authenticated.id,
            superseded_count=int(superseded),
        )

    pending_auth_ref = generate_secure_token(nbytes=24)
    otp_code = generate_otp(settings.otp_length)
    db.add(AuthOtpRecord(
        id=pending_auth_ref,
        user_id=authenticated.id,
        purpose=_OTP_PURPOSE_LOGIN_MFA,
        code_hash=hash_token(otp_code),
        expires_at=now + timedelta(minutes=settings.otp_expire_minutes),
        ip_address=_truncate(ip_address, _IP_MAX),
        user_agent=_truncate(user_agent, _USER_AGENT_MAX),
    ))
    _record_audit(
        db,
        event_type="otp_requested",
        outcome="success",
        user_id=authenticated.id,
        ip_address=ip_address,
        user_agent=user_agent,
        metadata={"purpose": _OTP_PURPOSE_LOGIN_MFA, "throttled": False},
    )
    db.commit()

    _send_email_safe(
        authenticated.email,
        "Your sign-in code",
        _otp_email_body(otp_code),
        context="login_otp",
    )
    return PendingLogin(
        pending_auth_ref=pending_auth_ref,
        expires_in_minutes=settings.otp_expire_minutes,
    )


def resend_login_otp(
    db: Session,
    *,
    pending_auth_ref: str,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> PendingLogin:
    """Re-issue an OTP for an existing pending-auth flow.

    Rotates the code in place (the pending_auth_ref is stable), resets
    the attempt counter, and re-sends the email — subject to the
    configured resend interval. If the interval has not passed, returns
    the same ref without sending a new email.

    Never reveals whether the ref was valid: an unknown or already-used
    ref produces the same shape of response as a successful resend.
    """
    row = (
        db.query(AuthOtpRecord)
        .filter(AuthOtpRecord.id == pending_auth_ref)
        .with_for_update()
        .first()
    )

    fallback = PendingLogin(
        pending_auth_ref=pending_auth_ref,
        expires_in_minutes=settings.otp_expire_minutes,
    )

    # Same lock-release discipline as verify_login_otp: every early
    # return after the FOR UPDATE must end the transaction so the row
    # is not left locked for the caller's session lifetime.
    if (
        row is None
        or row.used_at is not None
        or row.purpose != _OTP_PURPOSE_LOGIN_MFA
    ):
        db.rollback()
        return fallback

    now = _utcnow()
    row_expires = _as_utc(row.expires_at)
    if row_expires is None or row_expires <= now:
        db.rollback()
        return fallback

    row_created = _as_utc(row.created_at)
    within_interval = (
        (now - row_created).total_seconds()
        < settings.otp_resend_interval_seconds
    )
    if within_interval:
        _record_audit(
            db,
            event_type="otp_requested",
            outcome="success",
            user_id=row.user_id,
            ip_address=ip_address,
            user_agent=user_agent,
            metadata={"purpose": _OTP_PURPOSE_LOGIN_MFA, "throttled": True, "resend": True},
        )
        db.commit()
        remaining = max(1, int((row_expires - now).total_seconds() / 60))
        return PendingLogin(
            pending_auth_ref=pending_auth_ref,
            expires_in_minutes=remaining,
        )

    user = db.get(User, row.user_id)
    if user is None:
        return fallback

    new_code = generate_otp(settings.otp_length)
    row.code_hash = hash_token(new_code)
    row.expires_at = now + timedelta(minutes=settings.otp_expire_minutes)
    # The `created_at` column doubles as the throttle anchor for OTP
    # records: rotating the code also resets the "issued at" time so the
    # next resend is throttled relative to this new code, not the very
    # first one.
    row.created_at = now
    row.attempt_count = 0
    row.last_attempt_at = None
    _record_audit(
        db,
        event_type="otp_requested",
        outcome="success",
        user_id=user.id,
        ip_address=ip_address,
        user_agent=user_agent,
        metadata={"purpose": _OTP_PURPOSE_LOGIN_MFA, "throttled": False, "resend": True},
    )
    db.commit()

    _send_email_safe(
        user.email,
        "Your sign-in code",
        _otp_email_body(new_code),
        context="resend_login_otp",
    )
    return PendingLogin(
        pending_auth_ref=pending_auth_ref,
        expires_in_minutes=settings.otp_expire_minutes,
    )


# ---------------------------------------------------------------------------
# Login — OTP verification (issues tokens)
# ---------------------------------------------------------------------------
def verify_login_otp(
    db: Session,
    *,
    pending_auth_ref: str,
    code: str,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> IssuedTokens:
    """Stage 2 of login: verify the OTP and issue access + refresh tokens.

    The pending_auth_ref must be the ref returned by `initiate_login`. It
    cannot be replaced with an access token, a refresh token, or any
    other credential type — the lookup is against the OTP row id with
    purpose = 'login_mfa', which only that endpoint produces.

    Single-use: the row is marked used_at on success. A concurrent second
    verification sees used_at and is rejected. Failed attempts increment
    the row's attempt_count; when the configured maximum is reached the
    row is invalidated (used_at set) and further attempts with the same
    ref fail regardless of the code.
    """
    row = (
        db.query(AuthOtpRecord)
        .filter(AuthOtpRecord.id == pending_auth_ref)
        .with_for_update()
        .first()
    )

    # Every early exit after the FOR UPDATE must release the row lock,
    # or the next transaction touching the same row blocks. The `row is
    # None` case acquired no lock (empty result set), but rollback is
    # still correct and cheap. The `used_at` and `purpose` cases DO
    # acquire a lock on an existing row and MUST release it before
    # raising; without this, a second attempt on a consumed OTP leaves
    # the row locked for the caller's session lifetime.
    if row is None or row.purpose != _OTP_PURPOSE_LOGIN_MFA:
        db.rollback()
        raise OtpVerificationFailed(_GENERIC_OTP_ERROR)

    if row.used_at is not None:
        db.rollback()
        raise OtpVerificationFailed(_GENERIC_OTP_ERROR)

    now = _utcnow()
    row_expires = _as_utc(row.expires_at)
    if row_expires is None or row_expires <= now:
        row.used_at = now
        _record_audit(
            db,
            event_type="otp_failed",
            outcome="failure",
            user_id=row.user_id,
            ip_address=ip_address,
            user_agent=user_agent,
            metadata={"reason": "expired"},
        )
        db.commit()
        raise OtpVerificationFailed(_GENERIC_OTP_ERROR)

    if (row.attempt_count or 0) >= settings.otp_max_attempts:
        row.used_at = now
        _record_audit(
            db,
            event_type="otp_failed",
            outcome="failure",
            user_id=row.user_id,
            ip_address=ip_address,
            user_agent=user_agent,
            metadata={"reason": "attempts_exceeded"},
        )
        db.commit()
        raise OtpVerificationFailed(_GENERIC_OTP_ERROR)

    presented = hash_token(code)
    if not constant_time_equal(presented, row.code_hash):
        row.attempt_count = (row.attempt_count or 0) + 1
        row.last_attempt_at = now
        if row.attempt_count >= settings.otp_max_attempts:
            row.used_at = now
        _record_audit(
            db,
            event_type="otp_failed",
            outcome="failure",
            user_id=row.user_id,
            ip_address=ip_address,
            user_agent=user_agent,
            metadata={
                "reason": "wrong_code",
                "attempt": row.attempt_count,
                "max_attempts": settings.otp_max_attempts,
            },
        )
        db.commit()
        raise OtpVerificationFailed(_GENERIC_OTP_ERROR)

    # Success.
    user = db.get(User, row.user_id)
    if user is None:
        row.used_at = now
        db.commit()
        raise OtpVerificationFailed(_GENERIC_OTP_ERROR)

    row.used_at = now
    user.last_login_at = now
    user.failed_login_count = 0
    user.locked_until = None

    access_token = create_access_token(user.id)
    refresh_raw = _issue_refresh_token(
        db,
        user_id=user.id,
        ip_address=ip_address,
        user_agent=user_agent,
    )

    _record_audit(
        db,
        event_type="otp_verified",
        outcome="success",
        user_id=user.id,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    _record_audit(
        db,
        event_type="login_succeeded",
        outcome="success",
        user_id=user.id,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.commit()

    return IssuedTokens(
        access_token=access_token,
        refresh_token=refresh_raw,
        access_expires_in_minutes=settings.access_token_expire_minutes,
        refresh_expires_in_days=settings.refresh_token_expire_days,
    )


# ---------------------------------------------------------------------------
# Refresh-token rotation
# ---------------------------------------------------------------------------
def refresh_tokens(
    db: Session,
    *,
    raw_refresh_token: str,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> IssuedTokens:
    """Rotate a refresh token and issue a new access token.

    Every successful refresh revokes the presented token and issues a
    new one in the same family. Presenting a token that was already
    revoked triggers reuse detection: the entire family is revoked and
    an audit event is recorded. No new tokens are issued on reuse.

    Concurrent requests presenting the same token are serialized by a
    row-level lock on the `auth_refresh_tokens` row. Exactly one
    request rotates; the other observes the revocation and is treated
    as a reuse event (this is the strict interpretation the locked
    architecture requires — there is no grace window).
    """
    token_hash = hash_token(raw_refresh_token)
    row = (
        db.query(AuthRefreshToken)
        .filter(AuthRefreshToken.token_hash == token_hash)
        .with_for_update()
        .first()
    )

    if row is None:
        _record_audit(
            db,
            event_type="refresh_failed",
            outcome="failure",
            ip_address=ip_address,
            user_agent=user_agent,
            metadata={"reason": "unknown"},
        )
        db.commit()
        raise SessionExpired("Session expired. Please sign in again.")

    if row.revoked_at is not None:
        # Reuse of an already-revoked token: treat as theft. Revoke the
        # whole family so no member of it can be used again.
        family_id = row.family_id
        now = _utcnow()
        db.query(AuthRefreshToken).filter(
            AuthRefreshToken.family_id == family_id,
            AuthRefreshToken.revoked_at.is_(None),
        ).update(
            {"revoked_at": now, "revoked_reason": "reuse_detected"},
            synchronize_session=False,
        )
        _record_audit(
            db,
            event_type="refresh_token_reuse_detected",
            outcome="failure",
            user_id=row.user_id,
            ip_address=ip_address,
            user_agent=user_agent,
            metadata={"family_id": family_id},
        )
        db.commit()
        raise SessionExpired("Session expired. Please sign in again.")

    now = _utcnow()
    row_expires = _as_utc(row.expires_at)
    if row_expires is None or row_expires <= now:
        row.revoked_at = now
        row.revoked_reason = "expired"
        _record_audit(
            db,
            event_type="refresh_failed",
            outcome="failure",
            user_id=row.user_id,
            ip_address=ip_address,
            user_agent=user_agent,
            metadata={"reason": "expired"},
        )
        db.commit()
        raise SessionExpired("Session expired. Please sign in again.")

    user = db.get(User, row.user_id)
    if user is None:
        row.revoked_at = now
        row.revoked_reason = "user_deleted"
        db.commit()
        raise SessionExpired("Session expired. Please sign in again.")

    # Rotate.
    row.revoked_at = now
    row.revoked_reason = "rotated"
    row.last_used_at = now

    new_raw = _issue_refresh_token(
        db,
        user_id=user.id,
        family_id=row.family_id,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    access_token = create_access_token(user.id)

    _record_audit(
        db,
        event_type="refresh_succeeded",
        outcome="success",
        user_id=user.id,
        ip_address=ip_address,
        user_agent=user_agent,
        metadata={"family_id": row.family_id},
    )
    db.commit()

    return IssuedTokens(
        access_token=access_token,
        refresh_token=new_raw,
        access_expires_in_minutes=settings.access_token_expire_minutes,
        refresh_expires_in_days=settings.refresh_token_expire_days,
    )


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------
def logout(db: Session, *, raw_refresh_token: str) -> None:
    """Revoke the presented refresh token.

    Idempotent: an unknown token or a token that was already revoked is a
    no-op. The client is expected to clear its cookie regardless.
    """
    token_hash = hash_token(raw_refresh_token)
    row = (
        db.query(AuthRefreshToken)
        .filter(AuthRefreshToken.token_hash == token_hash)
        .with_for_update()
        .first()
    )

    if row is None or row.revoked_at is not None:
        return

    row.revoked_at = _utcnow()
    row.revoked_reason = "logout"
    _record_audit(
        db,
        event_type="logout",
        outcome="success",
        user_id=row.user_id,
    )
    db.commit()


def logout_all_devices(db: Session, *, user: User) -> int:
    """Revoke every active refresh session for the user.

    Returns the number of sessions revoked. The audit history is
    preserved (only the refresh-token rows are touched). Access tokens
    issued previously remain valid until they expire — the locked
    architecture is short-lived access tokens plus a server-side
    revocable refresh layer, not a global access-token denylist.
    """
    now = _utcnow()
    revoked = (
        db.query(AuthRefreshToken)
        .filter(
            AuthRefreshToken.user_id == user.id,
            AuthRefreshToken.revoked_at.is_(None),
        )
        .update(
            {"revoked_at": now, "revoked_reason": "logout_all"},
            synchronize_session=False,
        )
    )
    _record_audit(
        db,
        event_type="logout_all",
        outcome="success",
        user_id=user.id,
        metadata={"revoked_count": int(revoked or 0)},
    )
    db.commit()
    return int(revoked or 0)


# ---------------------------------------------------------------------------
# Password reset
# ---------------------------------------------------------------------------
def request_password_reset(
    db: Session,
    *,
    email: str,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> None:
    """Request a password-reset email.

    Enumeration-resistant: always returns normally. No email is sent for
    an unknown address; the audit log records the attempt so operators
    can see enumeration patterns without exposing them to the client.

    Supersedes prior unused reset tokens for the same user so only the
    newest link works.
    """
    user = user_service.get_user_by_email(db, email)

    if user is None:
        _record_audit(
            db,
            event_type="password_reset_requested",
            outcome="failure",
            ip_address=ip_address,
            user_agent=user_agent,
            metadata={"reason": "unknown_email"},
        )
        db.commit()
        return

    now = _utcnow()

    # Per-target throttle. This is the same control that
    # resend_verification_email and initiate_login already apply to their
    # own email sends: even from many IPs, an attacker cannot cause more
    # than one reset email per user within the configured resend
    # interval. A throttled request is a no-op that still returns the
    # enumeration-resistant success response — it does NOT reveal that
    # the target exists or that it was recently emailed.
    latest = (
        db.query(AuthPasswordResetToken)
        .filter(AuthPasswordResetToken.user_id == user.id)
        .order_by(AuthPasswordResetToken.created_at.desc())
        .first()
    )
    if latest is not None:
        age = (now - _as_utc(latest.created_at)).total_seconds()
        if age < settings.otp_resend_interval_seconds:
            _record_audit(
                db,
                event_type="password_reset_requested",
                outcome="success",
                user_id=user.id,
                ip_address=ip_address,
                user_agent=user_agent,
                metadata={"throttled": True},
            )
            db.commit()
            return

    db.query(AuthPasswordResetToken).filter(
        AuthPasswordResetToken.user_id == user.id,
        AuthPasswordResetToken.used_at.is_(None),
    ).update({"used_at": now}, synchronize_session=False)

    raw_token = generate_secure_token()
    db.add(AuthPasswordResetToken(
        id=uuid.uuid4().hex,
        user_id=user.id,
        token_hash=hash_token(raw_token),
        expires_at=now + timedelta(minutes=settings.password_reset_expire_minutes),
    ))
    _record_audit(
        db,
        event_type="password_reset_requested",
        outcome="success",
        user_id=user.id,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.commit()

    _send_email_safe(
        user.email,
        "Reset your password",
        _password_reset_email_body(user, raw_token),
        context="password_reset",
    )


def complete_password_reset(
    db: Session,
    *,
    raw_token: str,
    new_password: str,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> User:
    """Reset the password with the raw token from the reset email.

    The token is single-use. On success the password is updated via the
    existing bcrypt path, all active refresh sessions for the user are
    revoked, and the failed-login / lockout state is cleared. The token
    is marked used ONLY on the successful branch; a failed lookup or an
    expired token leaves it unchanged (or marks expired tokens used so
    they cannot be retried).
    """
    token_hash = hash_token(raw_token)
    row = (
        db.query(AuthPasswordResetToken)
        .filter(AuthPasswordResetToken.token_hash == token_hash)
        .with_for_update()
        .first()
    )

    if row is None or row.used_at is not None:
        # Release the FOR UPDATE lock before raising; see the comment
        # in verify_login_otp for the full reasoning.
        db.rollback()
        raise InvalidOrExpiredToken(_GENERIC_TOKEN_ERROR)

    now = _utcnow()
    row_expires = _as_utc(row.expires_at)
    if row_expires is None or row_expires <= now:
        row.used_at = now
        db.commit()
        raise InvalidOrExpiredToken(_GENERIC_TOKEN_ERROR)

    user = db.get(User, row.user_id)
    if user is None:
        row.used_at = now
        db.commit()
        raise InvalidOrExpiredToken(_GENERIC_TOKEN_ERROR)

    user.hashed_password = hash_password(new_password)
    user.failed_login_count = 0
    user.locked_until = None
    row.used_at = now

    db.query(AuthRefreshToken).filter(
        AuthRefreshToken.user_id == user.id,
        AuthRefreshToken.revoked_at.is_(None),
    ).update(
        {"revoked_at": now, "revoked_reason": "password_reset"},
        synchronize_session=False,
    )

    _record_audit(
        db,
        event_type="password_reset_completed",
        outcome="success",
        user_id=user.id,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.commit()
    return user


__all__ = [
    "AuthError",
    "InvalidOrExpiredToken",
    "IssuedTokens",
    "LoginFailed",
    "OtpVerificationFailed",
    "PendingLogin",
    "SessionExpired",
    "SignupOutcome",
    "complete_password_reset",
    "initiate_login",
    "logout",
    "logout_all_devices",
    "refresh_tokens",
    "request_password_reset",
    "resend_login_otp",
    "resend_verification_email",
    "signup",
    "verify_email",
    "verify_login_otp",
]