from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_minutes: int


class UserOut(BaseModel):
    id: str
    email: str
    name: str | None = None
    profile_picture_url: str | None = None
    created_at: datetime


class ProfileUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    profile_picture_url: str | None = Field(default=None, max_length=2048)


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)
