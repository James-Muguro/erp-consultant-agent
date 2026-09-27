"""
Generic SMTP email provider - works with any standard SMTP server
(Gmail, Outlook/Microsoft 365, Zoho, a corporate relay, a vendor's own
SMTP endpoint) purely through configuration. Switching SMTP vendors
never touches this file - only SMTP_HOST/PORT/USERNAME/PASSWORD/
USE_TLS/USE_SSL change.

This is the ONLY module in the application that imports `smtplib`. The
auth service calls `src.email.service.send_email`, which dispatches
here only when `settings.email_provider == "smtp"` - no authentication
or business-logic code imports this module directly.

Security posture:
  * The password is read from `settings.smtp_password` and never
    written to a log line, exception message, or API response.
  * Failure messages are reduced to the exception class name; the
    server's response text is discarded.
  * Only the recipient's domain is logged, never the local part.
  * The message body is never logged.
"""
from __future__ import annotations

import smtplib
from email.message import EmailMessage
from email.policy import default as _default_policy
from typing import List

from src.config.settings import settings
from src.email.exceptions import EmailDeliveryError, EmailNotConfigured
from src.utils.logger import get_logger

logger = get_logger(__name__)

_PROVIDER_NAME = "smtp"
_CONNECT_TIMEOUT_SECONDS = 15


def _recipient_domain(to: str) -> str:
    if "@" not in to:
        return "invalid"
    domain = to.rsplit("@", 1)[-1].strip()
    return domain or "invalid"


def validate_configuration(settings_obj) -> List[str]:
    """Called once at startup when email_provider == 'smtp' and
    delivery is enabled. Returns problem strings; empty means fully
    configured."""
    problems: List[str] = []
    if settings_obj.smtp_use_tls and settings_obj.smtp_use_ssl:
        problems.append("smtp_use_tls and smtp_use_ssl are mutually exclusive")
    if not (settings_obj.smtp_use_tls or settings_obj.smtp_use_ssl):
        problems.append("SMTP must use TLS or SSL")
    if not settings_obj.smtp_host:
        problems.append("smtp_host")
    if not settings_obj.smtp_username:
        problems.append("smtp_username")
    if not settings_obj.smtp_password:
        problems.append("smtp_password")
    if not settings_obj.smtp_from_address:
        problems.append("smtp_from_address")
    return problems


def _require_configured() -> None:
    if not getattr(settings, "email_delivery_enabled", False):
        raise EmailNotConfigured(
            "Email delivery is disabled (EMAIL_DELIVERY_ENABLED is false)."
        )
    missing = validate_configuration(settings)
    if missing:
        raise EmailNotConfigured("SMTP configuration is incomplete: " + ", ".join(missing) + ".")


def _build_message(to: str, subject: str, body: str) -> EmailMessage:
    message = EmailMessage(policy=_default_policy)
    message["From"] = settings.smtp_from_address
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body, subtype="plain", charset="utf-8")
    return message


def _deliver(message: EmailMessage) -> None:
    host = settings.smtp_host
    port = settings.smtp_port

    if settings.smtp_use_ssl:
        with smtplib.SMTP_SSL(host, port, timeout=_CONNECT_TIMEOUT_SECONDS) as connection:
            connection.login(settings.smtp_username, settings.smtp_password)
            connection.send_message(message)
    else:
        with smtplib.SMTP(host, port, timeout=_CONNECT_TIMEOUT_SECONDS) as connection:
            connection.ehlo()
            if settings.smtp_use_tls:
                connection.starttls()
                connection.ehlo()
            connection.login(settings.smtp_username, settings.smtp_password)
            connection.send_message(message)


def send_via_smtp(to: str, subject: str, body: str) -> None:
    """Deliver a plain-text email via SMTP, using whatever host/port/
    credentials are currently configured - works unchanged for any
    SMTP-speaking vendor."""
    if not isinstance(to, str) or not to.strip():
        raise EmailDeliveryError("Recipient address is empty or invalid.")

    _require_configured()
    message = _build_message(to, subject, body)

    try:
        _deliver(message)
    except (smtplib.SMTPException, OSError) as e:
        logger.warning(
            "Email delivery failed",
            provider=_PROVIDER_NAME,
            recipient_domain=_recipient_domain(to),
            failure_class=type(e).__name__,
        )
        raise EmailDeliveryError(f"SMTP delivery failed ({type(e).__name__}).") from None
    else:
        logger.info(
            "Email delivered",
            provider=_PROVIDER_NAME,
            recipient_domain=_recipient_domain(to),
        )


__all__ = ["send_via_smtp", "validate_configuration"]