"""
Unit tests for the email abstraction and its Gmail SMTP provider.

Scope: only `src.email.service` and `src.email.gmail_smtp`. No network
access, no real credentials, no app, no DB. `smtplib.SMTP` and
`smtplib.SMTP_SSL` are mocked in every provider test.

Coverage:
    Abstraction (`send_email`)
        - dispatches to the installed provider
        - rejects empty / whitespace-only / non-string recipients
        - rejects non-string subject and body
        - the default provider is used when none is installed
        - `reset_email_provider` restores the default

    Provider (`send_via_gmail_smtp`)
        - builds a message with the configured From, and the passed
          To, Subject, and body
        - the body content round-trips (including UTF-8)
        - TLS branch calls SMTP(host, port, timeout) then starttls()
        - SSL branch calls SMTP_SSL(host, port, timeout) and does NOT
          call starttls()
        - authentication uses the configured username and password
        - success returns normally
        - SMTPException is converted to EmailDeliveryError
        - OSError is converted to EmailDeliveryError
        - the app password does not appear in the raised error text
        - the original SMTP response text does not appear in the raised
          error text
        - the app password does not appear in any log call
        - the message body does not appear in any log call
        - recipient local part is never logged (domain only)
        - EmailNotConfigured when delivery is disabled
        - EmailNotConfigured when a required SMTP field is missing
        - empty recipient rejected before any SMTP call
"""
from __future__ import annotations

import smtplib
from unittest.mock import MagicMock, patch

import pytest

from src.config.settings import settings
from src.email import (
    EmailDeliveryError,
    EmailNotConfigured,
    reset_email_provider,
    send_email,
    set_email_provider,
)
from src.email import gmail_smtp


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _reset_provider_between_tests():
    """Guarantee a clean provider state for every test. Without this, a
    test that installs a fake provider could leak into an unrelated
    test through import-time module state."""
    reset_email_provider()
    yield
    reset_email_provider()


@pytest.fixture
def smtp_settings(monkeypatch):
    """Configure `settings` as a fully-configured Gmail SMTP deployment.

    Uses monkeypatch so the modifications are undone at teardown and no
    test leaks configuration into another. These are the settings
    validation in Step 3 would have accepted, with obviously-fake
    credentials so a leaked assertion would be obvious.
    """
    monkeypatch.setattr(settings, "email_delivery_enabled", True)
    monkeypatch.setattr(settings, "smtp_host", "smtp.gmail.com")
    monkeypatch.setattr(settings, "smtp_port", 587)
    monkeypatch.setattr(settings, "smtp_username", "sender@example.com")
    monkeypatch.setattr(settings, "smtp_password", "app-password-secret")
    monkeypatch.setattr(settings, "smtp_from_address", "sender@example.com")
    monkeypatch.setattr(settings, "smtp_use_tls", True)
    monkeypatch.setattr(settings, "smtp_use_ssl", False)
    yield


def _install_smtp_mock(mock_cls: MagicMock) -> MagicMock:
    """Wire a mocked SMTP class so it behaves as a context manager whose
    __enter__ returns a fresh MagicMock, and whose __exit__ does NOT
    suppress exceptions raised inside the block.

    The explicit `__exit__.return_value = None` is deliberate: a
    MagicMock's default __exit__ return value is falsy in current
    Python, but setting it explicitly means the failure-path tests do
    not depend on that implementation detail.
    """
    instance = MagicMock()
    mock_cls.return_value.__enter__.return_value = instance
    mock_cls.return_value.__exit__.return_value = None
    return instance


# ---------------------------------------------------------------------------
# Abstraction: dispatch
# ---------------------------------------------------------------------------
class TestSendEmailDispatch:
    def test_dispatches_to_installed_provider(self):
        received: list[tuple[str, str, str]] = []

        def fake_provider(to: str, subject: str, body: str) -> None:
            received.append((to, subject, body))

        set_email_provider(fake_provider)
        send_email("recipient@example.com", "Hello", "Body text")

        assert received == [("recipient@example.com", "Hello", "Body text")]

    def test_reset_restores_default(self, monkeypatch):
        # Force email_delivery_enabled=False so the default Gmail
        # provider reaches the configuration gate and raises
        # EmailNotConfigured, independent of the ambient .env or a
        # setting left over from another test in the same file.
        monkeypatch.setattr(settings, "email_delivery_enabled", False)

        calls: list[tuple[str, str, str]] = []
        set_email_provider(lambda to, s, b: calls.append((to, s, b)))
        reset_email_provider()

        with pytest.raises(EmailNotConfigured):
            send_email("recipient@example.com", "Hello", "Body")
        assert calls == []

    def test_provider_exception_propagates(self):
        """A provider that raises must not be silently swallowed: the
        caller needs to know whether the message was handed off."""
        def failing_provider(to: str, subject: str, body: str) -> None:
            raise EmailDeliveryError("provider refused")

        set_email_provider(failing_provider)
        with pytest.raises(EmailDeliveryError):
            send_email("recipient@example.com", "Hello", "Body")


# ---------------------------------------------------------------------------
# Abstraction: validation
# ---------------------------------------------------------------------------
class TestSendEmailValidation:
    def test_rejects_empty_recipient(self):
        called: list[tuple[str, str, str]] = []
        set_email_provider(lambda to, s, b: called.append((to, s, b)))

        with pytest.raises(EmailDeliveryError):
            send_email("", "Hello", "Body")
        with pytest.raises(EmailDeliveryError):
            send_email("   ", "Hello", "Body")
        assert called == []

    def test_rejects_non_string_recipient(self):
        called: list[tuple[str, str, str]] = []
        set_email_provider(lambda to, s, b: called.append((to, s, b)))

        with pytest.raises(EmailDeliveryError):
            send_email(None, "Hello", "Body")  # type: ignore[arg-type]
        with pytest.raises(EmailDeliveryError):
            send_email(123, "Hello", "Body")  # type: ignore[arg-type]
        assert called == []

    def test_rejects_non_string_subject_or_body(self):
        set_email_provider(lambda to, s, b: None)
        with pytest.raises(EmailDeliveryError):
            send_email("recipient@example.com", None, "Body")  # type: ignore[arg-type]
        with pytest.raises(EmailDeliveryError):
            send_email("recipient@example.com", "Subject", None)  # type: ignore[arg-type]

    def test_does_not_rewrite_recipient(self):
        """The abstraction must not normalize the recipient. It passes
        the value through byte-for-byte so the caller (and the eventual
        To header) sees exactly what was supplied."""
        seen: list[str] = []
        set_email_provider(lambda to, s, b: seen.append(to))

        send_email("MixedCase@Example.COM", "S", "B")
        assert seen == ["MixedCase@Example.COM"]


# ---------------------------------------------------------------------------
# Provider: message construction
# ---------------------------------------------------------------------------
class TestGmailProviderMessage:
    @patch("src.email.gmail_smtp.smtplib.SMTP")
    def test_sets_from_to_subject_and_body(self, mock_smtp_cls, smtp_settings):
        instance = _install_smtp_mock(mock_smtp_cls)

        gmail_smtp.send_via_gmail_smtp(
            "recipient@example.com", "Test subject", "Test body"
        )

        message = instance.send_message.call_args.args[0]
        assert message["From"] == "sender@example.com"
        assert message["To"] == "recipient@example.com"
        assert message["Subject"] == "Test subject"
        assert message.get_content_type() == "text/plain"
        assert message.get_content().strip() == "Test body"

    @patch("src.email.gmail_smtp.smtplib.SMTP")
    def test_utf8_body_round_trips(self, mock_smtp_cls, smtp_settings):
        """Non-ASCII body content must round-trip. The provider must
        never silently mangle a body that will sometimes contain
        account names, timestamps, or links with query parameters."""
        instance = _install_smtp_mock(mock_smtp_cls)

        gmail_smtp.send_via_gmail_smtp(
            "recipient@example.com", "Subject", "Voilà — code ☕ 123456"
        )

        message = instance.send_message.call_args.args[0]
        assert "☕" in message.get_content()
        assert "123456" in message.get_content()

    @patch("src.email.gmail_smtp.smtplib.SMTP")
    def test_utf8_subject_is_encoded_not_crashed(self, mock_smtp_cls, smtp_settings):
        """A non-ASCII subject must serialize without raising. The exact
        encoding is policy-dependent; the invariant is that the message
        serializes cleanly and the ASCII-safe portion survives."""
        instance = _install_smtp_mock(mock_smtp_cls)

        gmail_smtp.send_via_gmail_smtp(
            "recipient@example.com", "Café résumé", "Body"
        )

        message = instance.send_message.call_args.args[0]
        # as_bytes() forces the header encoder to run; if it raises, the
        # test fails here rather than in production.
        raw = message.as_bytes()
        assert b"Body" in raw


# ---------------------------------------------------------------------------
# Provider: transport
# ---------------------------------------------------------------------------
class TestGmailProviderTransport:
    @patch("src.email.gmail_smtp.smtplib.SMTP")
    def test_tls_branch_uses_smtp_and_starttls(self, mock_smtp_cls, smtp_settings):
        instance = _install_smtp_mock(mock_smtp_cls)

        gmail_smtp.send_via_gmail_smtp(
            "recipient@example.com", "Subject", "Body"
        )

        # Host and port from settings; timeout is the module constant.
        mock_smtp_cls.assert_called_once_with("smtp.gmail.com", 587, timeout=15)
        # STARTTLS was requested after EHLO.
        instance.ehlo.assert_called()
        instance.starttls.assert_called_once()

    @patch("src.email.gmail_smtp.smtplib.SMTP")
    def test_ssl_branch_uses_smtp_ssl(
        self, mock_smtp_cls, smtp_settings, monkeypatch
    ):
        monkeypatch.setattr(settings, "smtp_use_tls", False)
        monkeypatch.setattr(settings, "smtp_use_ssl", True)
        monkeypatch.setattr(settings, "smtp_port", 465)
        instance = _install_smtp_mock(mock_smtp_cls)

        with patch("src.email.gmail_smtp.smtplib.SMTP_SSL") as mock_ssl_cls:
            ssl_instance = _install_smtp_mock(mock_ssl_cls)
            gmail_smtp.send_via_gmail_smtp(
                "recipient@example.com", "Subject", "Body"
            )

        mock_smtp_cls.assert_not_called()
        mock_ssl_cls.assert_called_once_with("smtp.gmail.com", 465, timeout=15)
        # No explicit STARTTLS on an already-encrypted connection.
        ssl_instance.starttls.assert_not_called()
        ssl_instance.send_message.assert_called_once()

    @patch("src.email.gmail_smtp.smtplib.SMTP")
    def test_login_uses_configured_credentials(self, mock_smtp_cls, smtp_settings):
        instance = _install_smtp_mock(mock_smtp_cls)

        gmail_smtp.send_via_gmail_smtp(
            "recipient@example.com", "Subject", "Body"
        )

        instance.login.assert_called_once_with(
            "sender@example.com", "app-password-secret"
        )

    @patch("src.email.gmail_smtp.smtplib.SMTP")
    def test_success_returns_normally(self, mock_smtp_cls, smtp_settings):
        _install_smtp_mock(mock_smtp_cls)
        # Should not raise.
        gmail_smtp.send_via_gmail_smtp(
            "recipient@example.com", "Subject", "Body"
        )


# ---------------------------------------------------------------------------
# Provider: error conversion
# ---------------------------------------------------------------------------
class TestGmailProviderErrors:
    @patch("src.email.gmail_smtp.smtplib.SMTP")
    def test_smtp_exception_converted_to_delivery_error(
        self, mock_smtp_cls, smtp_settings
    ):
        instance = _install_smtp_mock(mock_smtp_cls)
        instance.send_message.side_effect = smtplib.SMTPException(
            "provider responded with an internal string"
        )

        with pytest.raises(EmailDeliveryError):
            gmail_smtp.send_via_gmail_smtp(
                "recipient@example.com", "Subject", "Body"
            )

    @patch("src.email.gmail_smtp.smtplib.SMTP")
    def test_oserror_converted_to_delivery_error(
        self, mock_smtp_cls, smtp_settings
    ):
        mock_smtp_cls.side_effect = OSError("connection refused by peer")

        with pytest.raises(EmailDeliveryError):
            gmail_smtp.send_via_gmail_smtp(
                "recipient@example.com", "Subject", "Body"
            )

    @patch("src.email.gmail_smtp.smtplib.SMTP")
    def test_password_never_in_exception_text(
        self, mock_smtp_cls, smtp_settings
    ):
        instance = _install_smtp_mock(mock_smtp_cls)
        instance.login.side_effect = smtplib.SMTPAuthenticationError(
            535, b"authentication failed"
        )

        with pytest.raises(EmailDeliveryError) as exc_info:
            gmail_smtp.send_via_gmail_smtp(
                "recipient@example.com", "Subject", "Body"
            )

        text = str(exc_info.value)
        assert "app-password-secret" not in text
        # And the provider's response text is not surfaced either.
        assert "authentication failed" not in text

    @patch("src.email.gmail_smtp.smtplib.SMTP")
    def test_smtp_response_text_never_in_exception(
        self, mock_smtp_cls, smtp_settings
    ):
        instance = _install_smtp_mock(mock_smtp_cls)
        instance.send_message.side_effect = smtplib.SMTPException(
            "550 5.7.1 <recipient@example.com> blocked by provider policy"
        )

        with pytest.raises(EmailDeliveryError) as exc_info:
            gmail_smtp.send_via_gmail_smtp(
                "recipient@example.com", "Subject", "Body"
            )

        text = str(exc_info.value)
        assert "550 5.7.1" not in text
        assert "blocked by provider policy" not in text
        # The failure class name IS present - that is the useful signal.
        assert "SMTPException" in text


# ---------------------------------------------------------------------------
# Provider: logging discipline
# ---------------------------------------------------------------------------
class TestGmailProviderLogging:
    @patch("src.email.gmail_smtp.smtplib.SMTP")
    def test_no_password_or_body_in_any_log_call(
        self, mock_smtp_cls, smtp_settings
    ):
        """Even on failure, the app password and the message body must
        never appear in a log record."""
        instance = _install_smtp_mock(mock_smtp_cls)
        instance.send_message.side_effect = smtplib.SMTPException("boom")

        with patch.object(gmail_smtp, "logger") as mock_logger:
            with pytest.raises(EmailDeliveryError):
                gmail_smtp.send_via_gmail_smtp(
                    "recipient@example.com",
                    "Test subject",
                    "This is the sensitive body containing an OTP 123456",
                )

        rendered = repr(mock_logger.mock_calls)
        assert "app-password-secret" not in rendered
        assert "sensitive body" not in rendered
        assert "123456" not in rendered

    @patch("src.email.gmail_smtp.smtplib.SMTP")
    def test_only_recipient_domain_is_logged(
        self, mock_smtp_cls, smtp_settings
    ):
        instance = _install_smtp_mock(mock_smtp_cls)
        instance.send_message.side_effect = smtplib.SMTPException("boom")

        with patch.object(gmail_smtp, "logger") as mock_logger:
            with pytest.raises(EmailDeliveryError):
                gmail_smtp.send_via_gmail_smtp(
                    "alice.smith@example.com", "S", "B"
                )

        rendered = repr(mock_logger.mock_calls)
        # Domain is present (its log-line purpose).
        assert "example.com" in rendered
        # Local part is not.
        assert "alice.smith" not in rendered
        assert "alice.smith@example.com" not in rendered

    @patch("src.email.gmail_smtp.smtplib.SMTP")
    def test_success_logs_once_without_body(
        self, mock_smtp_cls, smtp_settings
    ):
        _install_smtp_mock(mock_smtp_cls)

        with patch.object(gmail_smtp, "logger") as mock_logger:
            gmail_smtp.send_via_gmail_smtp(
                "recipient@example.com", "Subject", "Sensitive body"
            )

        # Exactly one log line on success.
        assert mock_logger.info.call_count == 1
        rendered = repr(mock_logger.mock_calls)
        assert "Sensitive body" not in rendered


# ---------------------------------------------------------------------------
# Provider: configuration gate
# ---------------------------------------------------------------------------
class TestGmailProviderConfiguration:
    def test_raises_when_delivery_disabled(self, monkeypatch):
        monkeypatch.setattr(settings, "email_delivery_enabled", False)
        with pytest.raises(EmailNotConfigured):
            gmail_smtp.send_via_gmail_smtp(
                "recipient@example.com", "S", "B"
            )

    def test_raises_when_required_field_missing(self, monkeypatch, smtp_settings):
        monkeypatch.setattr(settings, "smtp_host", None)
        with pytest.raises(EmailNotConfigured) as exc_info:
            gmail_smtp.send_via_gmail_smtp(
                "recipient@example.com", "S", "B"
            )
        assert "smtp_host" in str(exc_info.value)

    def test_raises_when_multiple_fields_missing(self, monkeypatch, smtp_settings):
        monkeypatch.setattr(settings, "smtp_username", None)
        monkeypatch.setattr(settings, "smtp_password", None)
        with pytest.raises(EmailNotConfigured) as exc_info:
            gmail_smtp.send_via_gmail_smtp(
                "recipient@example.com", "S", "B"
            )
        text = str(exc_info.value)
        assert "smtp_username" in text
        assert "smtp_password" in text

    @patch("src.email.gmail_smtp.smtplib.SMTP")
    def test_empty_recipient_rejected_before_smtp_call(
        self, mock_smtp_cls, smtp_settings
    ):
        """The provider must reject an empty recipient before touching
        smtplib. Asserting the SMTP class was not constructed proves no
        connection was attempted."""
        with pytest.raises(EmailDeliveryError):
            gmail_smtp.send_via_gmail_smtp("", "S", "B")
        with pytest.raises(EmailDeliveryError):
            gmail_smtp.send_via_gmail_smtp("   ", "S", "B")
        mock_smtp_cls.assert_not_called()