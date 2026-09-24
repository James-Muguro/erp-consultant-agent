"""
Auth request and response schemas.

Password policy
---------------
Creation and password change enforce minimum length 12, maximum 128,
rejection of all-whitespace, a small in-app common-password list, and
rejection of passwords that contain the email's local part. Composition
rules are deliberately not enforced (NIST 800-63B deprecates them).

Login does NOT enforce the creation-time minimum, so accounts created
before a policy change continue to authenticate.

Email normalization
-------------------
Email is lowercased on both signup and login.

Signup account type
-------------------
SignupRequest.account_type selects one of five account choices. For the
four individual choices, the value is the initial application role
granted to the new user. For AccountType.ORGANIZATION, the value
triggers the tenant creation flow: the user gets the ERP_USER
application role and becomes the Owner of a newly-created
Organization. 'Organization' is never persisted as a UserRole.
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


# ---------------------------------------------------------------------------
# Password policy
# ---------------------------------------------------------------------------
PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_LENGTH = 128

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
    # The account choice made at signup. Always required: a user with no
    # application role would be locked out of every guarded route, so
    # the flow refuses to create one.
    account_type: AccountType
    # Required only when account_type == AccountType.ORGANIZATION; the
    # validator below enforces that. Ignored for individual signups.
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
        """When the caller selected an organization account, the
        organization's display name is required so we do not create a
        nameless tenant. Whitespace-only is rejected."""
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
# Response models
# ---------------------------------------------------------------------------
class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in_minutes: int


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

    roles         — application roles the user currently holds, as
                    string values. Multiple entries are the norm.
    organizations — organizations the user is a member of, with the
                    membership role. Empty for users who have not
                    created or joined an organization.

    Not built directly from the ORM User row via from_attributes: the
    roles and organizations fields come from separate tables and must
    be assembled explicitly (see _build_user_out in orchestrator_api.py).
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