"""
Exception types for the email abstraction.

Kept in a separate module so both `service.py` (the abstraction) and
`gmail_smtp.py` (the concrete provider) can import the same types
without a circular import between them.

Exception messages intentionally never include SMTP credentials, the
message body, or raw provider responses. Provider-specific failures are
reduced to a failure-class name (e.g. 'SMTPAuthenticationError') that
is safe to surface to callers and to write to logs.
"""
from __future__ import annotations


class EmailError(Exception):
    """Base class for every error raised by this package.

    Callers that want a single catch-all should import this; callers
    that need to distinguish configuration errors from delivery
    failures should catch the subclasses.
    """


class EmailNotConfigured(EmailError):
    """Raised when a send is attempted before SMTP is fully configured.

    Turned into a clear error by the calling flow rather than a raw
    smtplib exception. A missing configuration is an operator problem,
    not a transient delivery failure, so it is kept distinct from
    EmailDeliveryError.
    """


class EmailDeliveryError(EmailError):
    """Raised when a configured provider fails to hand off a message.

    The message is intentionally opaque: it names the failure class
    (e.g. 'SMTPAuthenticationError') but not the provider's response
    text, the credentials used, or the message content.
    """