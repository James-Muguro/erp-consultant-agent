"""
Shared helpers for completing the full post-migration authentication
flow.

Flow: signup → verify-email → login → verify-otp. Returns the access
token issued by verify-otp.

Used by every test file that needs an authenticated user. Centralizing
it means a future contract change is a one-file change.
"""
from __future__ import annotations

from typing import List, Tuple

from fastapi.testclient import TestClient

from src.email import reset_email_provider, set_email_provider


def signup_and_authenticate(
    client: TestClient,
    *,
    email: str,
    password: str = "testpassword123",
    account_type: str = "functional_consultant",
    organization_name: str | None = None,
) -> str:
    """Complete the full auth flow and return the access token."""
    captured: List[Tuple[str, str, str]] = []

    def _capture(to: str, subject: str, body: str) -> None:
        captured.append((to, subject, body))

    set_email_provider(_capture)
    try:
        payload = {
            "email": email,
            "password": password,
            "account_type": account_type,
        }
        if organization_name is not None:
            payload["organization_name"] = organization_name

        r = client.post("/api/auth/signup", json=payload)
        assert r.status_code == 200, f"signup failed: {r.text}"

        raw_verify = captured[-1][2].split("token=")[1].split("\n")[0]
        r = client.post(
            "/api/auth/verify-email", json={"token": raw_verify}
        )
        assert r.status_code == 200, f"verify-email failed: {r.text}"

        r = client.post(
            "/api/auth/login",
            json={"email": email, "password": password},
        )
        assert r.status_code == 200, f"login failed: {r.text}"
        pending_ref = r.json()["pending_auth_ref"]

        otp_code = captured[-1][2].split("    ")[1].split("\n")[0].strip()

        r = client.post(
            "/api/auth/login/verify-otp",
            json={"pending_auth_ref": pending_ref, "code": otp_code},
        )
        assert r.status_code == 200, f"verify-otp failed: {r.text}"
        return r.json()["access_token"]
    finally:
        reset_email_provider()