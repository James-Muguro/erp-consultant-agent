"""
Generic HTTP-API email provider - works with any transactional email
API that accepts a JSON POST body and a static auth header (Brevo,
SendGrid, Postmark, Mailgun, and most others). Switching vendors never
touches this file: the request URL, auth header, and JSON body shape
are all configuration (EMAIL_HTTP_*), not code.

Not covered: providers requiring request-signing (AWS SES's HTTP API,
SigV4) or OAuth2 token exchange (Microsoft Graph). Those need real
signing/token logic that can't be expressed as a template - if you
need one of those, it genuinely does need its own module, same as
before.

Template substitution happens on the PARSED JSON structure, not on raw
text, so a subject or body containing quotes, braces, or newlines can
never break the JSON payload - it's substituted as a Python value and
re-serialized by httpx's own JSON encoder.

Security posture (mirrors smtp_provider.py):
  * The API key is read from settings and never logged, never included
    in an exception message.
  * Only the recipient's domain is logged, never the local part or the
    body.
"""
from __future__ import annotations

import json
from typing import Any, List

import httpx

from src.config.settings import settings
from src.email.exceptions import EmailDeliveryError, EmailNotConfigured
from src.utils.logger import get_logger

logger = get_logger(__name__)

_PROVIDER_NAME = "http_api"
_REQUEST_TIMEOUT_SECONDS = 15


def _recipient_domain(to: str) -> str:
    if "@" not in to:
        return "invalid"
    domain = to.rsplit("@", 1)[-1].strip()
    return domain or "invalid"


def validate_configuration(settings_obj) -> List[str]:
    """Called once at startup when email_provider == 'http_api' and
    delivery is enabled."""
    problems: List[str] = []
    if not settings_obj.email_http_api_url:
        problems.append("email_http_api_url")
    if not settings_obj.email_http_api_key:
        problems.append("email_http_api_key")
    if not settings_obj.email_http_from_address:
        problems.append("email_http_from_address")
    if not settings_obj.email_http_body_template:
        problems.append("email_http_body_template")
    else:
        try:
            json.loads(settings_obj.email_http_body_template)
        except (json.JSONDecodeError, TypeError):
            problems.append("email_http_body_template (not valid JSON)")
    if settings_obj.email_http_extra_headers:
        try:
            json.loads(settings_obj.email_http_extra_headers)
        except (json.JSONDecodeError, TypeError):
            problems.append("email_http_extra_headers (not valid JSON)")
    return problems


def _require_configured() -> None:
    if not getattr(settings, "email_delivery_enabled", False):
        raise EmailNotConfigured(
            "Email delivery is disabled (EMAIL_DELIVERY_ENABLED is false)."
        )
    missing = validate_configuration(settings)
    if missing:
        raise EmailNotConfigured(
            "HTTP API email configuration is incomplete: " + ", ".join(missing) + "."
        )


def _substitute(node: Any, context: dict[str, str]) -> Any:
    """Recursively substitute {{key}} placeholders inside string values
    of a parsed JSON structure (dict/list/str/other). Operates on
    already-parsed Python values, so the substituted content is later
    re-serialized to JSON safely - no manual escaping needed here."""
    if isinstance(node, str):
        result = node
        for key, value in context.items():
            result = result.replace(f"{{{{{key}}}}}", value)
        return result
    if isinstance(node, dict):
        return {k: _substitute(v, context) for k, v in node.items()}
    if isinstance(node, list):
        return [_substitute(v, context) for v in node]
    return node


def _build_request(to: str, subject: str, body: str) -> tuple[dict, dict]:
    context = {
        "to": to,
        "subject": subject,
        "body": body,
        "from_email": settings.email_http_from_address or "",
        "from_name": settings.email_http_from_name or "",
        "api_key": settings.email_http_api_key or "",
    }

    template = json.loads(settings.email_http_body_template)
    payload = _substitute(template, context)

    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    auth_header_name = settings.email_http_auth_header_name or "api-key"
    auth_header_prefix = settings.email_http_auth_header_prefix or ""
    headers[auth_header_name] = f"{auth_header_prefix}{settings.email_http_api_key}"

    if settings.email_http_extra_headers:
        extra = json.loads(settings.email_http_extra_headers)
        headers.update(_substitute(extra, context))

    return payload, headers


def send_via_http_api(to: str, subject: str, body: str) -> None:
    """Deliver a plain-text email via the configured HTTP API - works
    unchanged for any vendor whose payload shape you've described in
    EMAIL_HTTP_BODY_TEMPLATE."""
    if not isinstance(to, str) or not to.strip():
        raise EmailDeliveryError("Recipient address is empty or invalid.")

    _require_configured()
    payload, headers = _build_request(to, subject, body)

    try:
        response = httpx.post(
            settings.email_http_api_url,
            json=payload,
            headers=headers,
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        status = e.response.status_code if e.response is not None else "?"
        logger.warning(
            "Email delivery failed",
            provider=_PROVIDER_NAME,
            recipient_domain=_recipient_domain(to),
            failure_class=type(e).__name__,
            status_code=status,
        )
        raise EmailDeliveryError(f"HTTP API delivery failed (HTTP {status}).") from None
    except httpx.HTTPError as e:
        logger.warning(
            "Email delivery failed",
            provider=_PROVIDER_NAME,
            recipient_domain=_recipient_domain(to),
            failure_class=type(e).__name__,
        )
        raise EmailDeliveryError(f"HTTP API delivery failed ({type(e).__name__}).") from None
    else:
        logger.info(
            "Email delivered",
            provider=_PROVIDER_NAME,
            recipient_domain=_recipient_domain(to),
        )


__all__ = ["send_via_http_api", "validate_configuration"]