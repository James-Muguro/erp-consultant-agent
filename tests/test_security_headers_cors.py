"""
Step 8 tests for CORS configuration and security headers.

Scope: the CORSMiddleware settings in orchestrator_api.py, the
security_headers_middleware, and the specific headers the auth surface
requires. No live network access; all checks use the FastAPI TestClient.

Coverage:
    * CORS preflight returns the expected allow-origin, allow-methods,
      allow-headers, and allow-credentials headers.
    * CORS actual request from an allowed origin echoes that origin and
      sets Access-Control-Allow-Credentials: true.
    * CORS request from a disallowed origin does not receive the
      allow-origin header.
    * `expose_headers` includes X-Request-ID so the SPA can read it.
    * Common security headers present on HTML and JSON responses.
    * Content-Security-Policy present on HTML responses, absent on JSON
      responses, and absent on the auto-docs routes.
    * CSP contains the required directives and the Google Fonts origins.
    * Cache-Control: no-store on /api/auth/* responses; not set on
      non-auth responses.
    * HSTS present only when the request is HTTPS.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.db.base import init_db
from src.orchestrator_api import _CSP_POLICY, app


@pytest.fixture(scope="module", autouse=True)
def _ensure_schema():
    init_db()
    yield


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


# The default settings.allowed_origins is
# "http://localhost:3000,http://localhost:8000".
_ALLOWED_ORIGIN = "http://localhost:3000"
_DISALLOWED_ORIGIN = "https://evil.example.com"


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
class TestCors:
    def test_preflight_from_allowed_origin(self, client):
        r = client.options(
            "/api/auth/login",
            headers={
                "Origin": _ALLOWED_ORIGIN,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        assert r.status_code == 200
        assert r.headers.get("access-control-allow-origin") == _ALLOWED_ORIGIN
        assert r.headers.get("access-control-allow-credentials") == "true"
        allowed_methods = r.headers.get("access-control-allow-methods", "")
        assert "POST" in allowed_methods
        allowed_headers = r.headers.get("access-control-allow-headers", "").lower()
        assert "x-csrf-token" in allowed_headers
        assert "authorization" in allowed_headers

    def test_actual_request_from_allowed_origin(self, client):
        r = client.post(
            "/api/auth/login",
            json={"email": "nobody@example.com", "password": "wrongpass1234"},
            headers={"Origin": _ALLOWED_ORIGIN},
        )
        assert r.headers.get("access-control-allow-origin") == _ALLOWED_ORIGIN
        assert r.headers.get("access-control-allow-credentials") == "true"

    def test_actual_request_from_disallowed_origin(self, client):
        r = client.post(
            "/api/auth/login",
            json={"email": "nobody@example.com", "password": "wrongpass1234"},
            headers={"Origin": _DISALLOWED_ORIGIN},
        )
        # No CORS allow-origin header for an untrusted origin.
        assert r.headers.get("access-control-allow-origin") is None

    def test_expose_headers_includes_request_id(self, client):
        r = client.get(
            "/api/auth/me",
            headers={"Origin": _ALLOWED_ORIGIN},
        )
        exposed = r.headers.get("access-control-expose-headers", "").lower()
        assert "x-request-id" in exposed


# ---------------------------------------------------------------------------
# Security headers
# ---------------------------------------------------------------------------
class TestSecurityHeaders:
    _COMMON_HEADERS = {
        "x-content-type-options": "nosniff",
        "x-frame-options": "DENY",
        "referrer-policy": "strict-origin-when-cross-origin",
        "cross-origin-opener-policy": "same-origin",
    }

    def test_common_headers_on_html_response(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("text/html")
        for header, value in self._COMMON_HEADERS.items():
            assert r.headers.get(header) == value, f"missing {header}"

    def test_common_headers_on_json_response(self, client):
        r = client.post(
            "/api/auth/login",
            json={"email": "nobody@example.com", "password": "wrongpass1234"},
        )
        for header, value in self._COMMON_HEADERS.items():
            assert r.headers.get(header) == value, f"missing {header}"

    def test_permissions_policy_present(self, client):
        r = client.get("/")
        pp = r.headers.get("permissions-policy", "")
        assert "geolocation=()" in pp
        assert "microphone=()" in pp
        assert "camera=()" in pp

    def test_csp_on_html_response(self, client):
        r = client.get("/")
        assert r.headers.get("content-security-policy") == _CSP_POLICY

    def test_csp_contains_required_directives(self, client):
        r = client.get("/")
        csp = r.headers.get("content-security-policy", "")
        for directive in (
            "default-src 'self'",
            "script-src 'self'",
            "frame-ancestors 'none'",
            "base-uri 'self'",
            "form-action 'self'",
            "object-src 'none'",
        ):
            assert directive in csp, f"missing directive: {directive}"
        # Google Fonts origins must be present (index.html loads them).
        assert "https://fonts.googleapis.com" in csp
        assert "https://fonts.gstatic.com" in csp

    def test_csp_absent_on_json_response(self, client):
        r = client.post(
            "/api/auth/login",
            json={"email": "nobody@example.com", "password": "wrongpass1234"},
        )
        assert "content-security-policy" not in r.headers

    def test_csp_absent_on_docs(self, client):
        """The auto-generated docs routes render HTML but use inline
        scripts the strict CSP would break. They must be exempt."""
        r = client.get("/docs")
        # /docs may 200 (Swagger UI HTML) or be unavailable if disabled.
        if r.status_code == 200:
            assert "content-security-policy" not in r.headers


# ---------------------------------------------------------------------------
# Cache-Control on auth responses
# ---------------------------------------------------------------------------
class TestAuthCacheControl:
    def test_auth_login_response_has_no_store(self, client):
        r = client.post(
            "/api/auth/login",
            json={"email": "nobody@example.com", "password": "wrongpass1234"},
        )
        assert r.headers.get("cache-control") == "no-store"

    def test_auth_me_response_has_no_store(self, client):
        r = client.get("/api/auth/me")
        assert r.status_code == 401
        assert r.headers.get("cache-control") == "no-store"

    def test_non_auth_endpoint_does_not_get_no_store(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.headers.get("cache-control") != "no-store"


# ---------------------------------------------------------------------------
# HSTS
# ---------------------------------------------------------------------------
class TestHsts:
    def test_hsts_absent_on_http(self, client):
        """Plain-HTTP requests must not receive Strict-Transport-Security;
        the browser would ignore it and the header is semantically wrong
        for a non-TLS response."""
        r = client.get("/")
        assert "strict-transport-security" not in r.headers

    def test_hsts_present_when_x_forwarded_proto_is_https(self, client):
        """Behind a TLS-terminating proxy, the app sees HTTP but the
        original request was HTTPS. The middleware emits HSTS when the
        forwarded protocol is https."""
        r = client.get(
            "/",
            headers={"X-Forwarded-Proto": "https"},
        )
        hsts = r.headers.get("strict-transport-security", "")
        assert "max-age=" in hsts
        assert "includeSubDomains" in hsts