"""
Provider-independent email dispatch.

`send_email(to, subject, body)` is the only function the rest of the
application needs. It resolves the active provider (default: Gmail SMTP)
and delegates to it. The provider signature is the same as the
abstraction's own, so swapping providers is a one-line change and no
auth call site is touched.

Provider selection:
    * By default, `send_email` lazily imports `gmail_smtp` and uses
      `send_via_gmail_smtp`. The lazy import means importing this module
      does NOT require SMTP configuration and does NOT pull smtplib into
      the import graph of any module that only calls `send_email`.
    * `set_email_provider(fn)` installs a custom provider. Tests use it
      to intercept sends. Future providers (SendGrid, SES, Postmark)
      plug in the same way.
    * `reset_email_provider()` restores the default. Intended for test
      teardown; safe to call at any time.

Thread safety: provider installation is guarded by a lock, so a test
that installs a fake while another thread calls `send_email` sees a
consistent provider. The provider itself is invoked outside the lock so
a slow provider does not serialize unrelated sends.
"""
from __future__ import annotations

import threading
from typing import Callable

from src.email.exceptions import EmailDeliveryError
from src.utils.logger import get_logger

logger = get_logger(__name__)


# The provider contract. A provider is any callable that accepts
# (recipient, subject, body) and either returns normally on success or
# raises an EmailError subclass (or a subclass of Exception, which the
# abstraction converts to EmailDeliveryError below).
EmailProvider = Callable[[str, str, str], None]


_provider_lock = threading.Lock()
_provider: EmailProvider | None = None


def _default_provider() -> EmailProvider:
    """Import and return the default provider.

    Kept as a function rather than a module-level import so the Gmail
    module (and its `smtplib` import) is only pulled in when actually
    needed. A test that installs a fake provider never touches the
    Gmail module at all.
    """
    from src.email.gmail_smtp import send_via_gmail_smtp

    return send_via_gmail_smtp


def _resolve_provider() -> EmailProvider:
    with _provider_lock:
        if _provider is not None:
            return _provider
    return _default_provider()


def set_email_provider(provider: EmailProvider | None) -> None:
    """Install a provider callable, or pass None to restore the default.

    The provider must accept `(to: str, subject: str, body: str)` and
    return on success. Raising any exception is treated as a failure and
    propagated to the caller unchanged; the abstraction does not swallow
    or reinterpret provider exceptions beyond the empty-recipient check
    below.
    """
    global _provider
    with _provider_lock:
        _provider = provider


def reset_email_provider() -> None:
    """Restore the default provider. Intended for test teardown."""
    set_email_provider(None)


def send_email(to: str, subject: str, body: str) -> None:
    """Send a plain-text email through the active provider.

    Validation performed here is deliberately minimal: it rejects an
    empty or non-string recipient before any provider is invoked, and
    rejects non-string subject/body, so a caller with a malformed input
    gets an EmailDeliveryError instead of a provider-specific crash.
    Full email-address syntax validation is the responsibility of the
    API schema layer (`email-validator` via Pydantic), not this
    function - it does not attempt to be a second validation system.

    The recipient is never normalized or rewritten here: whatever the
    caller passes is what the provider receives and what appears in the
    To: header.
    """
    if not isinstance(to, str) or not to.strip():
        raise EmailDeliveryError("Recipient address is empty or invalid.")
    if not isinstance(subject, str):
        raise EmailDeliveryError("Email subject must be a string.")
    if not isinstance(body, str):
        raise EmailDeliveryError("Email body must be a string.")

    provider = _resolve_provider()
    provider(to, subject, body)