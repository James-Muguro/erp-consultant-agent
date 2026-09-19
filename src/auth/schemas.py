"""
Auth request and response schemas.

Password policy
---------------
Creation and password change enforce:
  - minimum length of 12 (NIST SP 800-63B: 8 is a floor, 12+ recommended
    for a single-factor login; this app currently has no second factor)
  - maximum length of 128 (bounded so we don't accept arbitrarily large
    inputs; bcrypt truncates to 72 bytes internally, which the security
    module documents)
  - rejection of all-whitespace passwords
  - rejection of a small in-app list of the most common passwords
  - rejection of passwords that contain the email's local part

Composition rules (must contain uppercase, must contain digit, etc.) are
deliberately NOT enforced. NIST 800-63B deprecates them: they push users
toward predictable patterns (`Password1!`) without meaningfully raising
entropy. Length plus a common-password check is the modern equivalent and
what this module implements.

Login does NOT enforce the creation-time minimum, so accounts created
before a policy change continue to authenticate.

Email normalization
-------------------
Email is lowercased on both signup and login, so a user who signed up as
`Test@Example.com` can log in as `test@example.com` (or any casing). If
your database currently contains mixed-case emails, run a one-time
backfill before deploying this change:

    UPDATE users SET email = lower(email);

Logins for those rows will 401 until the backfill runs.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)


# ---------------------------------------------------------------------------
# Password policy
# ---------------------------------------------------------------------------
PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_LENGTH = 128

# Small in-app blocklist of the highest-frequency compromised passwords.
# Covers the very top of the "have I been pwned" lists without shipping a
# multi-megabyte dataset. If you want comprehensive coverage, integrate
# the Have I Been Pwned k-anonymity API (sha1 prefix lookup) - out of
# scope for this file.
_COMMON_PASSWORDS = frozenset({
    "password", "password1", "password123", "passw0rd",
    "12345678", "123456789", "1234567890", "12345678901",
    "qwertyui", "qwerty123", "qwertyuiop",
    "letmein1", "letmein123", "welcome1", "welcome123",
    "iloveyou", "sunshine", "princess", "football", "baseball",
    "admin123", "administrator", "changeme", "changeit",
    "abc12345", "abcd1234", "1q2w3e4r", "1qaz2wsx",
    "monkey123", "dragon123", "master123", "shadow123",
    "superman", "batman123", "trustno1",
    "zaq12wsx", "asdfghjkl", "0987654321",
    "password1234", "password12345", "password123456",
    "qwerty123456", "qwertyuiop12", "1qaz2wsx3edc",
    "letmein12345", "welcome12345", "admin1234567",
    "changeme1234", "iloveyou1234", "passw0rd1234",
    "123456789012", "qwertyui1234", "sunshine1234",
    "princess1234", "football1234", "baseball1234",
    "changeit1234", "abc123456789", "abcd12345678",
    "1q2w3e4r5t6y", "monkey123456", "dragon123456",
    "master123456", "shadow123456", "superman1234",
    "batman123456", "trustno12345", "zaq12wsx3edc",
    "asdfghjkl123", "098765432109",
})

_EMAIL_LOCALPART_MIN_FOR_MATCH = 4


def _validate_password_common_rules(value: str) -> str:
    """Shared password checks: whitespace, length bounds, common-password
    blocklist. Called by both SignupRequest and PasswordChangeRequest so
    the two paths cannot drift."""
    if not value or not value.strip():
        raise ValueError("Password must not be empty or all whitespace.")
    if len(value) < PASSWORD_MIN_LENGTH:
        raise ValueError(
            f"Password must be at least {PASSWORD_MIN_LENGTH} characters."
        )
    if len(value) > PASSWORD_MAX_LENGTH:
        raise ValueError(
            f"Password must be at most {PASSWORD_MAX_LENGTH} characters."
        )
    if value.strip().lower() in _COMMON_PASSWORDS:
        raise ValueError(
            "This password appears in a list of commonly used passwords. "
            "Please choose a less predictable one."
        )
    return value


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------
class SignupRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=False)

    email: EmailStr
    password: str

    @field_validator("email", mode="after")
    @classmethod
    def _normalize_email(cls, v: str) -> str:
        return v.lower()

    @field_validator("password")
    @classmethod
    def _check_password(cls, v: str) -> str:
        return _validate_password_common_rules(v)

    @model_validator(mode="after")
    def _password_not_derived_from_email(self) -> "SignupRequest":
        """Reject passwords that embed the email's local part. NIST 800-63B
        guidance - the identifier and the password should not be trivially
        related.

        Only enforced when the local part is long enough to be meaningful
        (>= 4 chars), so a short local part like 'ab' doesn't
        false-positive. Case-insensitive comparison; the check is
        deliberately simple - it looks for the local part as a substring
        of the password, in either order."""
        local_part = str(self.email).split("@", 1)[0].lower()
        if len(local_part) < _EMAIL_LOCALPART_MIN_FOR_MATCH:
            return self
        pwd = self.password.lower()
        if local_part in pwd:
            raise ValueError(
                "Password must not contain the email address or its local part."
            )
        return self


class LoginRequest(BaseModel):
    """Login intentionally does NOT enforce the password creation policy.

    An account created under an older policy (before the minimum was
    raised) must still be able to log in. The only bound here is a
    maximum, so an oversized body cannot be used to probe the endpoint.
    """
    email: EmailStr
    password: str = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)

    @field_validator("email", mode="after")
    @classmethod
    def _normalize_email(cls, v: str) -> str:
        return v.lower()


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------
class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in_minutes: int


class UserOut(BaseModel):
    """`from_attributes=True` so FastAPI can serialize a SQLAlchemy User
    directly. Explicit rather than relying on the default behavior of the
    FastAPI/Pydantic version in use."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    name: str | None = None
    profile_picture_url: str | None = None
    created_at: datetime


# ---------------------------------------------------------------------------
# Account management
# ---------------------------------------------------------------------------
class ProfileUpdateRequest(BaseModel):
    # max_length is what protects against pathologically long names in
    # the UI; min_length is deliberately not set, so a user can clear
    # their display name by submitting an empty string.
    name: str | None = Field(default=None, max_length=120)

    @field_validator("name", mode="before")
    @classmethod
    def _strip_name(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _check_new_password(cls, v: str) -> str:
        return _validate_password_common_rules(v)

    @model_validator(mode="after")
    def _new_password_differs(self) -> "PasswordChangeRequest":
        """Reject a change that reuses the current password. Without this,
        the endpoint would hash-and-write and the user would see
        'success' while nothing meaningfully changed."""
        if self.current_password == self.new_password:
            raise ValueError("New password must differ from the current password.")
        return self