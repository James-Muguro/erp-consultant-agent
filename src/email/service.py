"""
Provider-independent email dispatch.

There are exactly two transports: SMTP and HTTP API. Every vendor -
Gmail, Outlook, Brevo, SendGrid, Postmark, whatever comes next - is a
configuration of one of these two, never a new code file. This module
never names a vendor.
"""
from __future__ import annotations

import threading
from typing import Callable

from src.config.settings import settings
from src.email.exceptions import EmailDeliveryError, EmailNotConfigured
from src.utils.logger import get_logger

logger = get_logger(__name__)

EmailProvider = Callable[[str, str, str], None]

_provider_lock = threading.Lock()
_provider: EmailProvider | None = None


def _default_provider() -> EmailProvider:
    transport = (getattr(settings, "email_provider", None) or "smtp").strip().lower()
    if transport == "smtp":
        from src.email.smtp_provider import send_via_smtp
        return send_via_smtp
    if transport == "http_api":
        from src.email.http_api_provider import send_via_http_api
        return send_via_http_api
    raise EmailNotConfigured(
        f"Unsupported EMAIL_PROVIDER {transport!r}. Must be 'smtp' or 'http_api'."
    )


def _resolve_provider() -> EmailProvider:
    with _provider_lock:
        if _provider is not None:
            return _provider
    return _default_provider()


def set_email_provider(provider: EmailProvider | None) -> None:
    global _provider
    with _provider_lock:
        _provider = provider


def reset_email_provider() -> None:
    set_email_provider(None)


def send_email(to: str, subject: str, body: str) -> None:
    if not isinstance(to, str) or not to.strip():
        raise EmailDeliveryError("Recipient address is empty or invalid.")
    if not isinstance(subject, str):
        raise EmailDeliveryError("Email subject must be a string.")
    if not isinstance(body, str):
        raise EmailDeliveryError("Email body must be a string.")

    provider = _resolve_provider()
    provider(to, subject, body)