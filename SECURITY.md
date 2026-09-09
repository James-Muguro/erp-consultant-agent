# Security

This document describes the security measures in place, and known
limitations - written to be accurate, not aspirational. Last reviewed
alongside the Stage 8 security pass.

## Authentication & authorization

- Per-user accounts (email + password), passwords hashed with bcrypt.
  Passwords are truncated to bcrypt's 72-byte limit before hashing (the
  standard, documented way to use bcrypt safely) - see `src/auth/security.py`.
- Access tokens are JWTs (HS256), signed with `JWT_SECRET_KEY`. The app
  **refuses to start** if that key is under 32 characters or matches a
  known placeholder value - see `src/config/settings.py`. Generate a real
  one with `openssl rand -hex 32`.
- No refresh-token flow yet - a token simply expires
  (`ACCESS_TOKEN_EXPIRE_MINUTES`, default 24h) and the user logs in again.
- Every project/session is scoped to the user who created it. Accessing
  another user's session returns `404`, never `403` - the API never
  confirms a session ID exists to someone who doesn't own it (see
  `_get_owned_session` in `src/orchestrator_api.py`).

## Transport & headers

Every response gets `X-Content-Type-Options: nosniff`, `X-Frame-Options:
DENY`, `Referrer-Policy: strict-origin-when-cross-origin`,
`Permissions-Policy` (denies geolocation/microphone/camera), and
`Strict-Transport-Security`.

**Not yet set: Content-Security-Policy.** This app serves both its own
frontend and FastAPI's built-in `/docs` (Swagger UI, which loads CDN
scripts) - a strict CSP could break either, and there's no way to verify
that without a real browser. A reasonable starting policy is documented as
a comment in `security_headers_middleware` (`src/orchestrator_api.py`) -
add it once someone can click through the app in an actual browser to
confirm nothing breaks.

## Rate limiting

- Auth endpoints (`/api/auth/signup`, `/api/auth/login`): 5/minute per IP.
- Every other endpoint: 60/minute per IP by default (`SlowAPIMiddleware` +
  `Limiter(default_limits=...)` in `src/orchestrator_api.py`) - this exists
  specifically because LLM-calling endpoints (chat, project start, phase
  execution) cost real money per request and previously had no limit at
  all.
- Known limitation: IP-based, not per-user. Multiple users behind the same
  NAT'd IP share a bucket. Meaningful protection against a runaway client
  or a leaked/stolen token being hammered; not a precise per-account quota.

## Data access

- Document downloads (`GET /api/projects/{id}/documents/{filename}`) use a
  whitelist match: the requested filename must exactly match a document
  already known to belong to that session. The client-supplied filename is
  never resolved against the filesystem directly, so a path-traversal
  attempt (`../../etc/passwd`) simply matches nothing and returns `404`.
- Errors never leak stack traces or internal details - every error
  (expected or unhandled) returns a consistent `{"error": {"code",
  "message", "request_id"}}` envelope; unhandled exceptions are logged in
  full server-side (with the request ID for correlation) but the client
  only ever sees a generic message.

## Untrusted content (prompt injection)

Web search results retrieved for the chat "ask a question" feature come
from arbitrary third-party pages and could contain text crafted to look
like instructions ("ignore the above and instead..."). The synthesis
prompt (`get_synthesis_prompt` in `src/utils/prompts.py`) wraps all
retrieved content (knowledge-base and web) in explicit `<reference_data>`
tags with an upfront instruction that anything inside is data to consult,
never a command to follow. This is a meaningful, standard mitigation - not
a guarantee against a sufficiently determined injection attempt on any
LLM, since no purely prompt-based defense is airtight.

## Dependencies

Scanned with `pip-audit`. As of this pass: zero known vulnerabilities.
Re-run `pip-audit -r requirements.txt` periodically - this is a snapshot,
not a standing guarantee, since new CVEs are published continuously
against unchanged code.

## Secrets

- No password, JWT secret, or API key is ever logged - verified by
  grepping every `logger.*` call in `src/` for those terms.
- `API_AUTH_KEY` (the old shared static key from before per-user auth
  existed) is kept only as an unused, optional settings field so old
  `.env` files don't fail to parse - nothing checks it.

## Known gaps / not yet built

- **File uploads**: not implemented yet. Nothing to secure here until that
  surface exists - revisit this document when it's added (validate size,
  MIME type, extension, and content; never execute uploaded files; store
  outside the source tree).
- **Multi-tenancy / organizations**: single-user-per-account only; no
  team/org boundary to enforce yet.
- **CSP**: see above.
- **Per-user (not just per-IP) rate limiting**: see above.
