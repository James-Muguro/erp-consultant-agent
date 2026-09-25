"""
Auth request and response schemas.

Password policy
---------------
Creation and password change enforce:
  - minimum length of 12 (NIST SP 800-63B: 12+ recommended for a
    single-factor login)
  - maximum length of 128
  - rejection of all-whitespace passwords
  - rejection of a small in-app list of the most common passwords
  - rejection of passwords that contain the email's local part

Composition rules (must contain uppercase, must contain digit, etc.)
are deliberately NOT enforced. NIST 800-63B deprecates them.

Login does NOT enforce the creation-time minimum, so accounts created
before a policy change continue to authenticate.

Email normalization
-------------------
Email is lowercased on signup, login, resend, and password reset.
Every schema in this module that accepts an email address applies the
same normalization.

Signup account type
-------------------
SignupRequest.account_type selects one of five account choices:

  * ERP_USER, FUNCTIONAL_CONSULTANT, DEVELOPER, MARKETER — the new
    user is granted the matching single application role via a
    UserRoleRecord. The four individual roles are separate; there is no
    combined-role concept.

  * ORGANIZATION — the tenant creation flow. An Organization row is
    created and the signing-up user receives an OrganizationMembership
    with role='owner'. The user receives NO application role.
    'Organization' is a tenant context, not an application role; it is
    never persisted as a UserRole.

    The two axes — application roles and organization membership roles —
    are independent and are not combined in any way.

MFA and token shape
-------------------
The MFA login flow has a two-step contract:

  1. POST /api/auth/login submits email+password and returns a
     LoginResponse containing an opaque `pending_auth_ref`. This is NOT
     an access token. It identifies a short-lived pending-auth flow and
     is only accepted by /api/auth/login/verify-otp.

  2. POST /api/auth/login/verify-otp submits the pending_auth_ref and
     the OTP code and returns a TokenResponse (access token in body) and
     sets the refresh cookie. Only this response grants authenticated
     access.

The refresh token is never present in any request or response body.
It is issued and consumed exclusively via the configured HttpOnly
cookie.

Response models never include:
  * password fields
  * raw refresh tokens
  * raw email-verification tokens
  * raw password-reset tokens
  * OTP codes
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Literal, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)

from src.auth.permissions import AccountType
from src.config.settings import settings


# ---------------------------------------------------------------------------
# Password policy
# ---------------------------------------------------------------------------
PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_LENGTH = 128

# OTP length is configured (settings.otp_length, default 6). Read once at
# import; the value is fixed at process startup, matching every other
# auth setting. Do not hardcode a different OTP length anywhere else.
OTP_LENGTH = settings.otp_length

# Small in-app blocklist of the highest-frequency compromised passwords.
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
    blocklist. Called by every schema that accepts a new password so the
    flows cannot drift."""
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
# Request models - signup / login
# ---------------------------------------------------------------------------
class SignupRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=False)

    email: EmailStr
    password: str
    # The account choice made at signup. Required for all five choices.
    # For individual choices this maps 1:1 to an application role. For
    # the ORGANIZATION choice it selects the tenant creation flow, which
    # grants the new user NO application role and creates an owner
    # membership instead. See the module docstring.
    account_type: AccountType
    # Required only when account_type == AccountType.ORGANIZATION.
    organization_name: Optional[str] = Field(default=None, max_length=200)

    @field_validator("email", mode="after")
    @classmethod
    def _normalize_email(cls, v: str) -> str:
        return v.lower()

    @field_validator("password")
    @classmethod
    def _check_password(cls, v: str) -> str:
        return _validate_password_common_rules(v)

    @field_validator("organization_name", mode="before")
    @classmethod
    def _strip_org_name(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v

    @model_validator(mode="after")
    def _password_not_derived_from_email(self) -> "SignupRequest":
        local_part = str(self.email).split("@", 1)[0].lower()
        if len(local_part) < _EMAIL_LOCALPART_MIN_FOR_MATCH:
            return self
        pwd = self.password.lower()
        if local_part in pwd:
            raise ValueError(
                "Password must not contain the email address or its local part."
            )
        return self

    @model_validator(mode="after")
    def _org_name_required_for_org_signup(self) -> "SignupRequest":
        if self.account_type is AccountType.ORGANIZATION:
            if not self.organization_name or not self.organization_name.strip():
                raise ValueError(
                    "Organization name is required when signing up as an "
                    "organization."
                )
        return self


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)

    @field_validator("email", mode="after")
    @classmethod
    def _normalize_email(cls, v: str) -> str:
        return v.lower()


# ---------------------------------------------------------------------------
# Request models - MFA
# ---------------------------------------------------------------------------
class VerifyOtpRequest(BaseModel):
    """Submit a pending-auth reference and an OTP code.

    `pending_auth_ref` is the opaque reference returned by
    POST /api/auth/login. It is NOT an access token; the field is
    deliberately named to make that explicit at every call site.

    `code` length is bound to the configured OTP length. A client-checkable
    "code must be N digits" error is safe — it reveals nothing about
    account existence.
    """
    pending_auth_ref: str = Field(..., min_length=1, max_length=200)
    code: str = Field(
        ...,
        min_length=OTP_LENGTH,
        max_length=OTP_LENGTH,
    )

    @field_validator("code")
    @classmethod
    def _digits_only(cls, v: str) -> str:
        if not v.isdigit():
            raise ValueError(
                f"Verification code must be exactly {OTP_LENGTH} digits."
            )
        return v


class ResendOtpRequest(BaseModel):
    pending_auth_ref: str = Field(..., min_length=1, max_length=200)


# ---------------------------------------------------------------------------
# Request models - email verification
# ---------------------------------------------------------------------------
class VerifyEmailRequest(BaseModel):
    # The token is presented by the user (from the emailed link). Length
    # bounded so a hostile body cannot be arbitrarily large.
    token: str = Field(..., min_length=1, max_length=512)


class ResendVerificationRequest(BaseModel):
    email: EmailStr

    @field_validator("email", mode="after")
    @classmethod
    def _normalize_email(cls, v: str) -> str:
        return v.lower()


# ---------------------------------------------------------------------------
# Request models - password reset
# ---------------------------------------------------------------------------
class PasswordResetRequestSchema(BaseModel):
    email: EmailStr

    @field_validator("email", mode="after")
    @classmethod
    def _normalize_email(cls, v: str) -> str:
        return v.lower()


class PasswordResetCompleteSchema(BaseModel):
    token: str = Field(..., min_length=1, max_length=512)
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _check_new_password(cls, v: str) -> str:
        return _validate_password_common_rules(v)


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------
class TokenResponse(BaseModel):
    """Issued only by the two flows that actually grant a session:
    /api/auth/login/verify-otp and /api/auth/refresh.

    Contains the access token in the response body. The refresh token is
    NOT present here — it is delivered exclusively via an HttpOnly
    cookie and is never visible to JavaScript.
    """
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in_minutes: int


class LoginResponse(BaseModel):
    """Response to a successful password verification.

    This does NOT grant authenticated access. `pending_auth_ref` is an
    opaque reference to a short-lived pending-authentication flow. It
    MUST NOT be used as an access token or refresh token; passing it to
    the JWT decoder or to /api/auth/refresh will fail. It is single-use
    and expires according to settings.pending_auth_expire_minutes.
    """
    pending_auth_ref: str
    expires_in_minutes: int
    message: str


class MessageResponse(BaseModel):
    """Generic success response.

    Used for every flow where a specific response would leak account
    existence: signup, resend verification, password-reset request,
    password-reset complete, logout, logout-all, verify-email.
    """
    message: str


class OrganizationSummary(BaseModel):
    """A single (organization, membership role) pair, as returned in the
    authenticated user's context. The role field is the ORGANIZATION
    role ('owner' | 'admin' | 'member'), which is a separate axis from
    the user's application roles."""
    id: str
    name: str
    role: str


class UserOut(BaseModel):
    """Authenticated user context returned by /api/auth/me and the
    profile endpoints.

    roles         — application roles the user currently holds.
    organizations — organizations the user is a member of, with the
                    membership role.

    Not built directly from the ORM User row via from_attributes: the
    roles and organizations fields come from separate tables and are
    assembled explicitly by _build_user_out.
    """
    model_config = ConfigDict(from_attributes=False)

    id: str
    email: str
    name: str | None = None
    profile_picture_url: str | None = None
    created_at: datetime
    roles: list[str] = Field(default_factory=list)
    organizations: list[OrganizationSummary] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Account management
# ---------------------------------------------------------------------------
class ProfileUpdateRequest(BaseModel):
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
        if self.current_password == self.new_password:
            raise ValueError("New password must differ from the current password.")
        return self


__all__ = [
    "LoginRequest",
    "LoginResponse",
    "MessageResponse",
    "OTP_LENGTH",
    "OrganizationSummary",
    "PASSWORD_MAX_LENGTH",
    "PASSWORD_MIN_LENGTH",
    "PasswordChangeRequest",
    "PasswordResetCompleteSchema",
    "PasswordResetRequestSchema",
    "ProfileUpdateRequest",
    "ResendOtpRequest",
    "ResendVerificationRequest",
    "SignupRequest",
    "TokenResponse",
    "UserOut",
    "VerifyEmailRequest",
    "VerifyOtpRequest",
]