"""
Email delivery abstraction.

Public API:
    send_email(to, subject, body)   - dispatch a plain-text email
    set_email_provider(provider)    - install a provider callable
    reset_email_provider()          - restore the default provider

Exceptions:
    EmailError               - base class for all email errors
    EmailNotConfigured       - SMTP is not fully configured
    EmailDeliveryError       - the provider failed to hand off a message

The authentication service layer depends on `send_email` and never
imports a concrete provider. Replacing Gmail SMTP with SendGrid, SES,
Postmark, or any other provider is a change to this package alone - no
call site in the auth service changes.
"""
from src.email.exceptions import (
    EmailDeliveryError,
    EmailError,
    EmailNotConfigured,
)
from src.email.service import (
    reset_email_provider,
    send_email,
    set_email_provider,
)

__all__ = [
    "EmailDeliveryError",
    "EmailError",
    "EmailNotConfigured",
    "reset_email_provider",
    "send_email",
    "set_email_provider",
]