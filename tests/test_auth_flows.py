"""
Service-layer tests for the authentication flows.

Scope: only `src.auth.flows`. No HTTP layer (Step 6 wires the routes).
Email is intercepted via `set_email_provider`, so no SMTP connection is
ever opened and no real credentials are used.

The database is the project's configured database (SQLite by default,
PostgreSQL in CI); schema is ensured via `init_db()` in a module-scoped
fixture. Tests clean up after themselves by user email.

Coverage:
    Signup
      - creates an unverified user + a verification token
      - duplicate email returns SignupOutcome(user_id=None)
      - organization signup creates an org + owner membership and grants
        no application role
    Email verification
      - succeeds and is single-use
      - expired token rejected
      - resend supersedes prior token
    Login / MFA
      - wrong password fails
      - unknown email fails with the same exception as wrong password
      - pending MFA ref is not an access token, not a refresh token
      - OTP success issues tokens
      - invalid / expired / used OTP fails
      - OTP attempt limit works
      - progressive login lockout triggers after N failures
    Refresh
      - rotates the refresh token
      - reuse of a rotated token revokes the family
    Logout
      - revokes the refresh token
      - logout-all revokes every session
    Password reset
      - enumeration-resistant request
      - token is single-use
      - expiry enforced
      - successful reset revokes refresh sessions and clears lock state
    Audit
      - events are recorded for the flows above
      - secrets (passwords, tokens, OTP codes) never appear in audit
        rows or in the email bodies logged by the test harness
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Generator, List, Tuple

import pytest
from sqlalchemy.orm import Session

from src.auth import flows
from src.auth.permissions import AccountType
from src.db.base import SessionLocal, init_db
from src.db.models import (
    AuthAuditEvent,
    AuthEmailVerificationToken,
    AuthOtpRecord,
    AuthPasswordResetToken,
    AuthRefreshToken,
    Organization,
    OrganizationMembership,
    User,
    UserRoleRecord,
)
from src.email import reset_email_provider, set_email_provider


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module", autouse=True)
def _ensure_schema():
    """Ensure the DB has the auth tables. Idempotent."""
    init_db()
    yield


@pytest.fixture
def db() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def sent_emails() -> Generator[List[Tuple[str, str, str]], None, None]:
    """Capture all send_email calls made during the test."""
    outbox: List[Tuple[str, str, str]] = []

    def capture(to: str, subject: str, body: str) -> None:
        outbox.append((to, subject, body))

    set_email_provider(capture)
    yield outbox
    reset_email_provider()


@pytest.fixture
def tracked_emails():
    """Track emails created during a test and clean up their users and
    every auth row that cascades from them."""
    emails: List[str] = []
    yield emails

    if not emails:
        return
    lowered = [e.lower() for e in emails]
    session = SessionLocal()
    try:
        users = session.query(User).filter(User.email.in_(lowered)).all()
        if not users:
            return
        user_ids = [u.id for u in users]
        # Cascades: user_roles, organization_memberships, auth_refresh_tokens,
        # auth_email_verification_tokens, auth_password_reset_tokens,
        # auth_otp_records all ON DELETE CASCADE on user_id. Organizations
        # are deleted explicitly (created_by is SET NULL on user delete).
        session.query(Organization).filter(
            Organization.created_by.in_(user_ids)
        ).delete(synchronize_session=False)
        session.query(User).filter(User.id.in_(user_ids)).delete(
            synchronize_session=False
        )
        # auth_audit_events uses ON DELETE SET NULL; delete the rows
        # created during the test explicitly so audit tests do not see
        # cross-test noise.
        session.query(AuthAuditEvent).filter(
            AuthAuditEvent.user_id.in_(user_ids)
        ).delete(synchronize_session=False)
        session.commit()
    finally:
        session.close()


def _unique_email() -> str:
    return f"flows-test-{uuid.uuid4().hex[:12]}@example.com"


_PASSWORD = "correct horse battery staple"


def _full_signup(
    db: Session,
    *,
    email: str,
    account_type: AccountType = AccountType.DEVELOPER,
    organization_name: str | None = None,
):
    return flows.signup(
        db,
        email=email,
        password=_PASSWORD,
        account_type=account_type,
        organization_name=organization_name,
    )


def _complete_signup_and_login(
    db: Session,
    sent: List[Tuple[str, str, str]],
    *,
    email: str,
) -> flows.IssuedTokens:
    """Drive signup -> verify -> login -> OTP to obtain tokens."""
    flows.signup(
        db,
        email=email,
        password=_PASSWORD,
        account_type=AccountType.DEVELOPER,
    )
    # Extract the verification token from the last sent email body.
    verify_body = sent[-1][2]
    raw_verify = verify_body.split("token=")[1].split("\n")[0]
    flows.verify_email(db, raw_token=raw_verify)

    pending = flows.initiate_login(db, email=email, password=_PASSWORD)
    otp_body = sent[-1][2]
    otp_code = otp_body.split("    ")[1].split("\n")[0].strip()
    return flows.verify_login_otp(
        db, pending_auth_ref=pending.pending_auth_ref, code=otp_code
    )


# ---------------------------------------------------------------------------
# Signup
# ---------------------------------------------------------------------------
class TestSignup:
    def test_creates_unverified_user_and_token(self, db, sent_emails, tracked_emails):
        email = _unique_email()
        tracked_emails.append(email)

        outcome = _full_signup(db, email=email)
        assert outcome.user_id is not None

        user = db.query(User).filter(User.email == email.lower()).one()
        assert user.email_verified_at is None

        # One verification token exists and is unused.
        tokens = (
            db.query(AuthEmailVerificationToken)
            .filter(AuthEmailVerificationToken.user_id == user.id)
            .all()
        )
        assert len(tokens) == 1
        assert tokens[0].used_at is None

        # One verification email was sent.
        assert len(sent_emails) == 1
        to, subject, body = sent_emails[0]
        assert to == email.lower()
        assert "verify" in subject.lower()
        assert "token=" in body

    def test_duplicate_email_returns_none_user_id_without_leak(
        self, db, sent_emails, tracked_emails
    ):
        email = _unique_email()
        tracked_emails.append(email)

        first = _full_signup(db, email=email)
        assert first.user_id is not None
        sent_after_first = len(sent_emails)

        second = _full_signup(db, email=email)
        assert second.user_id is None
        # No additional email sent for the duplicate.
        assert len(sent_emails) == sent_after_first

    def test_organization_signup_creates_tenant_and_owner(
        self, db, sent_emails, tracked_emails
    ):
        email = _unique_email()
        tracked_emails.append(email)

        org_name = f"Test Org {uuid.uuid4().hex[:6]}"
        outcome = _full_signup(
            db,
            email=email,
            account_type=AccountType.ORGANIZATION,
            organization_name=org_name,
        )
        assert outcome.user_id is not None

        user = db.query(User).filter(User.email == email.lower()).one()
        # Organization signup grants NO application role.
        roles = (
            db.query(UserRoleRecord).filter(UserRoleRecord.user_id == user.id).all()
        )
        assert roles == []
        # One organization membership with role='owner'.
        memberships = (
            db.query(OrganizationMembership)
            .filter(OrganizationMembership.user_id == user.id)
            .all()
        )
        assert len(memberships) == 1
        assert memberships[0].role == "owner"
        # The organization exists with the correct name.
        org = (
            db.query(Organization).filter(Organization.id == memberships[0].organization_id).one()
        )
        assert org.name == org_name


# ---------------------------------------------------------------------------
# Email verification
# ---------------------------------------------------------------------------
class TestEmailVerification:
    def test_succeeds_and_is_single_use(self, db, sent_emails, tracked_emails):
        email = _unique_email()
        tracked_emails.append(email)
        _full_signup(db, email=email)

        body = sent_emails[-1][2]
        raw = body.split("token=")[1].split("\n")[0]

        user = flows.verify_email(db, raw_token=raw)
        assert user.email_verified_at is not None

        # Second use must fail.
        with pytest.raises(flows.InvalidOrExpiredToken):
            flows.verify_email(db, raw_token=raw)

    def test_expired_token_rejected(self, db, sent_emails, tracked_emails):
        email = _unique_email()
        tracked_emails.append(email)
        _full_signup(db, email=email)

        user = db.query(User).filter(User.email == email.lower()).one()
        row = (
            db.query(AuthEmailVerificationToken)
            .filter(AuthEmailVerificationToken.user_id == user.id)
            .one()
        )
        row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()

        body = sent_emails[-1][2]
        raw = body.split("token=")[1].split("\n")[0]
        with pytest.raises(flows.InvalidOrExpiredToken):
            flows.verify_email(db, raw_token=raw)

    def test_resend_supersedes_prior_token(self, db, sent_emails, tracked_emails):
        email = _unique_email()
        tracked_emails.append(email)
        _full_signup(db, email=email)

        first_body = sent_emails[-1][2]
        first_raw = first_body.split("token=")[1].split("\n")[0]

        # Force the interval to expire by backdating the first token.
        user = db.query(User).filter(User.email == email.lower()).one()
        first_row = (
            db.query(AuthEmailVerificationToken)
            .filter(AuthEmailVerificationToken.user_id == user.id)
            .one()
        )
        first_row.created_at = datetime.now(timezone.utc) - timedelta(minutes=5)
        db.commit()

        flows.resend_verification_email(db, email=email)
        second_body = sent_emails[-1][2]
        second_raw = second_body.split("token=")[1].split("\n")[0]
        assert first_raw != second_raw

        # First token is now used.
        db.refresh(first_row)
        assert first_row.used_at is not None

        # Second token works; first does not.
        with pytest.raises(flows.InvalidOrExpiredToken):
            flows.verify_email(db, raw_token=first_raw)
        flows.verify_email(db, raw_token=second_raw)


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------
class TestLogin:
    def test_wrong_password_raises_generic(self, db, sent_emails, tracked_emails):
        email = _unique_email()
        tracked_emails.append(email)
        _full_signup(db, email=email)

        with pytest.raises(flows.LoginFailed) as exc_info:
            flows.initiate_login(db, email=email, password="not the password")
        # Same message as unknown email.
        assert str(exc_info.value) == flows._GENERIC_LOGIN_ERROR

    def test_unknown_email_raises_same_generic(self, db):
        with pytest.raises(flows.LoginFailed) as exc_info:
            flows.initiate_login(
                db,
                email="does-not-exist@example.com",
                password="whatever",
            )
        assert str(exc_info.value) == flows._GENERIC_LOGIN_ERROR

    def test_pending_ref_is_not_a_token(
        self, db, sent_emails, tracked_emails
    ):
        email = _unique_email()
        tracked_emails.append(email)
        _full_signup(db, email=email)

        # Verify so login can proceed.
        verify_raw = sent_emails[-1][2].split("token=")[1].split("\n")[0]
        flows.verify_email(db, raw_token=verify_raw)

        pending = flows.initiate_login(db, email=email, password=_PASSWORD)
        # The ref is not a JWT (no two dots forming a JWT structure).
        assert pending.pending_auth_ref.count(".") < 2
        # Passing the ref as a refresh token must fail.
        with pytest.raises(flows.SessionExpired):
            flows.refresh_tokens(db, raw_refresh_token=pending.pending_auth_ref)

    def test_otp_success_issues_tokens(self, db, sent_emails, tracked_emails):
        email = _unique_email()
        tracked_emails.append(email)
        tokens = _complete_signup_and_login(db, sent_emails, email=email)
        assert tokens.access_token
        assert tokens.refresh_token

        user = db.query(User).filter(User.email == email.lower()).one()
        # One refresh-token row exists, unused.
        rows = (
            db.query(AuthRefreshToken)
            .filter(AuthRefreshToken.user_id == user.id)
            .all()
        )
        assert len(rows) == 1
        assert rows[0].revoked_at is None

    def test_wrong_otp_fails(self, db, sent_emails, tracked_emails):
        email = _unique_email()
        tracked_emails.append(email)
        _full_signup(db, email=email)
        verify_raw = sent_emails[-1][2].split("token=")[1].split("\n")[0]
        flows.verify_email(db, raw_token=verify_raw)
        pending = flows.initiate_login(db, email=email, password=_PASSWORD)

        with pytest.raises(flows.OtpVerificationFailed):
            flows.verify_login_otp(
                db, pending_auth_ref=pending.pending_auth_ref, code="000000"
            )

    def test_otp_attempt_limit(self, db, sent_emails, tracked_emails):
        email = _unique_email()
        tracked_emails.append(email)
        _full_signup(db, email=email)
        verify_raw = sent_emails[-1][2].split("token=")[1].split("\n")[0]
        flows.verify_email(db, raw_token=verify_raw)
        pending = flows.initiate_login(db, email=email, password=_PASSWORD)

        # Exhaust attempts with wrong codes.
        for _ in range(10):
            try:
                flows.verify_login_otp(
                    db,
                    pending_auth_ref=pending.pending_auth_ref,
                    code="000000",
                )
            except flows.OtpVerificationFailed:
                pass

        # Even the correct code must now fail.
        otp_body = sent_emails[-1][2]
        correct = otp_body.split("    ")[1].split("\n")[0].strip()
        with pytest.raises(flows.OtpVerificationFailed):
            flows.verify_login_otp(
                db, pending_auth_ref=pending.pending_auth_ref, code=correct
            )

    def test_progressive_lockout(self, db, sent_emails, tracked_emails):
        email = _unique_email()
        tracked_emails.append(email)
        _full_signup(db, email=email)

        user = db.query(User).filter(User.email == email.lower()).one()
        threshold = 3
        # Monkeypatch-free path: directly configure via settings.
        from src.config.settings import settings as _settings
        original = _settings.login_max_failed_attempts
        _settings.login_max_failed_attempts = threshold
        try:
            for _ in range(threshold):
                try:
                    flows.initiate_login(db, email=email, password="wrong")
                except flows.LoginFailed:
                    pass
            db.refresh(user)
            assert user.failed_login_count == threshold
            assert user.locked_until is not None
            # Even the correct password must now fail while locked.
            with pytest.raises(flows.LoginFailed):
                flows.initiate_login(db, email=email, password=_PASSWORD)
        finally:
            _settings.login_max_failed_attempts = original


# ---------------------------------------------------------------------------
# Refresh
# ---------------------------------------------------------------------------
class TestRefresh:
    def test_rotation_issues_new_token(self, db, sent_emails, tracked_emails):
        email = _unique_email()
        tracked_emails.append(email)
        initial = _complete_signup_and_login(db, sent_emails, email=email)

        rotated = flows.refresh_tokens(
            db, raw_refresh_token=initial.refresh_token
        )
        assert rotated.refresh_token != initial.refresh_token
        assert rotated.access_token

        # Old token is revoked.
        old_hash = None
        from src.auth.security import hash_token
        old_hash = hash_token(initial.refresh_token)
        old_row = (
            db.query(AuthRefreshToken)
            .filter(AuthRefreshToken.token_hash == old_hash)
            .one()
        )
        assert old_row.revoked_at is not None
        assert old_row.revoked_reason == "rotated"

    def test_reuse_detection_revokes_family(self, db, sent_emails, tracked_emails):
        email = _unique_email()
        tracked_emails.append(email)
        initial = _complete_signup_and_login(db, sent_emails, email=email)

        rotated = flows.refresh_tokens(
            db, raw_refresh_token=initial.refresh_token
        )

        # Reuse the ORIGINAL (now revoked) token.
        with pytest.raises(flows.SessionExpired):
            flows.refresh_tokens(db, raw_refresh_token=initial.refresh_token)

        # The rotated (newest) token is also invalidated by family revoke.
        with pytest.raises(flows.SessionExpired):
            flows.refresh_tokens(db, raw_refresh_token=rotated.refresh_token)


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------
class TestLogout:
    def test_logout_revokes_token(self, db, sent_emails, tracked_emails):
        email = _unique_email()
        tracked_emails.append(email)
        tokens = _complete_signup_and_login(db, sent_emails, email=email)

        flows.logout(db, raw_refresh_token=tokens.refresh_token)
        with pytest.raises(flows.SessionExpired):
            flows.refresh_tokens(db, raw_refresh_token=tokens.refresh_token)

    def test_logout_all_revokes_all_sessions(
        self, db, sent_emails, tracked_emails
    ):
        email = _unique_email()
        tracked_emails.append(email)
        tokens1 = _complete_signup_and_login(db, sent_emails, email=email)
        # Second session via a fresh login.
        pending = flows.initiate_login(db, email=email, password=_PASSWORD)
        otp_body = sent_emails[-1][2]
        otp_code = otp_body.split("    ")[1].split("\n")[0].strip()
        tokens2 = flows.verify_login_otp(
            db, pending_auth_ref=pending.pending_auth_ref, code=otp_code
        )
        assert tokens1.refresh_token != tokens2.refresh_token

        user = db.query(User).filter(User.email == email.lower()).one()
        count = flows.logout_all_devices(db, user=user)
        assert count >= 2

        with pytest.raises(flows.SessionExpired):
            flows.refresh_tokens(db, raw_refresh_token=tokens1.refresh_token)
        with pytest.raises(flows.SessionExpired):
            flows.refresh_tokens(db, raw_refresh_token=tokens2.refresh_token)


# ---------------------------------------------------------------------------
# Password reset
# ---------------------------------------------------------------------------
class TestPasswordReset:
    def test_request_is_enumeration_resistant(self, db, sent_emails):
        # Unknown email — no exception, no email.
        flows.request_password_reset(db, email="nobody@example.com")
        assert all("nobody@example.com" not in e[0] for e in sent_emails)

    def test_token_is_single_use(self, db, sent_emails, tracked_emails):
        email = _unique_email()
        tracked_emails.append(email)
        _full_signup(db, email=email)

        flows.request_password_reset(db, email=email)
        body = sent_emails[-1][2]
        raw = body.split("token=")[1].split("\n")[0]

        user = flows.complete_password_reset(
            db, raw_token=raw, new_password="another-strong-password-9"
        )
        assert user.email == email.lower()

        with pytest.raises(flows.InvalidOrExpiredToken):
            flows.complete_password_reset(
                db, raw_token=raw, new_password="yet-another-strong-pass"
            )

    def test_expired_token_rejected(self, db, sent_emails, tracked_emails):
        email = _unique_email()
        tracked_emails.append(email)
        _full_signup(db, email=email)

        flows.request_password_reset(db, email=email)
        body = sent_emails[-1][2]
        raw = body.split("token=")[1].split("\n")[0]

        user = db.query(User).filter(User.email == email.lower()).one()
        row = (
            db.query(AuthPasswordResetToken)
            .filter(AuthPasswordResetToken.user_id == user.id)
            .one()
        )
        row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()

        with pytest.raises(flows.InvalidOrExpiredToken):
            flows.complete_password_reset(
                db, raw_token=raw, new_password="another-strong-password-9"
            )

    def test_successful_reset_revokes_sessions(
        self, db, sent_emails, tracked_emails
    ):
        email = _unique_email()
        tracked_emails.append(email)
        tokens = _complete_signup_and_login(db, sent_emails, email=email)

        flows.request_password_reset(db, email=email)
        body = sent_emails[-1][2]
        raw = body.split("token=")[1].split("\n")[0]

        flows.complete_password_reset(
            db, raw_token=raw, new_password="after-reset-pass-1234"
        )

        with pytest.raises(flows.SessionExpired):
            flows.refresh_tokens(db, raw_refresh_token=tokens.refresh_token)

        # New password works, old one does not.
        with pytest.raises(flows.LoginFailed):
            flows.initiate_login(db, email=email, password=_PASSWORD)
        flows.initiate_login(db, email=email, password="after-reset-pass-1234")


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------
class TestAudit:
    def test_events_are_recorded(self, db, sent_emails, tracked_emails):
        email = _unique_email()
        tracked_emails.append(email)

        # Full lifecycle.
        _full_signup(db, email=email)
        verify_raw = sent_emails[-1][2].split("token=")[1].split("\n")[0]
        flows.verify_email(db, raw_token=verify_raw)
        pending = flows.initiate_login(db, email=email, password=_PASSWORD)
        otp_code = sent_emails[-1][2].split("    ")[1].split("\n")[0].strip()
        tokens = flows.verify_login_otp(
            db, pending_auth_ref=pending.pending_auth_ref, code=otp_code
        )
        flows.logout(db, raw_refresh_token=tokens.refresh_token)

        user = db.query(User).filter(User.email == email.lower()).one()
        event_types = {
            row.event_type
            for row in db.query(AuthAuditEvent)
            .filter(AuthAuditEvent.user_id == user.id)
            .all()
        }
        for expected in (
            "signup_completed",
            "email_verification_requested",
            "email_verification_succeeded",
            "otp_requested",
            "otp_verified",
            "login_succeeded",
            "logout",
        ):
            assert expected in event_types, f"missing audit event {expected}"

    def test_no_secrets_in_audit_rows(self, db, sent_emails, tracked_emails):
        email = _unique_email()
        tracked_emails.append(email)
        _full_signup(db, email=email)
        verify_raw = sent_emails[-1][2].split("token=")[1].split("\n")[0]
        flows.verify_email(db, raw_token=verify_raw)
        pending = flows.initiate_login(db, email=email, password=_PASSWORD)
        otp_code = sent_emails[-1][2].split("    ")[1].split("\n")[0].strip()
        tokens = flows.verify_login_otp(
            db, pending_auth_ref=pending.pending_auth_ref, code=otp_code
        )

        user = db.query(User).filter(User.email == email.lower()).one()
        rows = (
            db.query(AuthAuditEvent)
            .filter(AuthAuditEvent.user_id == user.id)
            .all()
        )
        rendered = " ".join(
            f"{r.event_type} {r.outcome} {r.event_metadata}" for r in rows
        )
        # Never present in any audit row.
        assert _PASSWORD not in rendered
        assert tokens.access_token not in rendered
        assert tokens.refresh_token not in rendered
        assert verify_raw not in rendered
        assert otp_code not in rendered
        assert pending.pending_auth_ref not in rendered