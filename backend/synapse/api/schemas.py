"""Request bodies (validated by Pydantic)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from ..text.extract import EMAIL_RE

Mode = Literal["hybrid", "keyword", "semantic", "boolean"]
Role = Literal["viewer", "curator", "admin"]


def _email(value: str) -> str:
    value = value.strip().lower()
    if not EMAIL_RE.fullmatch(value):
        raise ValueError("Enter a valid e-mail address")
    return value


class RegisterBody(BaseModel):
    email: str
    name: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=8, max_length=200)

    _check_email = field_validator("email")(_email)


class LoginBody(BaseModel):
    email: str
    password: str


class ProfileBody(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    current_password: str | None = None
    new_password: str | None = Field(default=None, min_length=8, max_length=200)


class SubscriptionBody(BaseModel):
    query: str = Field(min_length=1, max_length=300)
    mode: Mode = "hybrid"
    min_score: float = Field(default=0.35, ge=0.05, le=0.95)


class SubscriptionPatch(BaseModel):
    active: bool | None = None
    min_score: float | None = Field(default=None, ge=0.05, le=0.95)


class BookmarkBody(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    note: str | None = Field(default=None, max_length=1000)


class FtpBody(BaseModel):
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(default=21, ge=1, le=65535)
    username: str = "anonymous"
    password: str = ""
    path: str = "/"
    pattern: str = "*"


class RemoteBody(BaseModel):
    provider: Literal["openalex", "arxiv"]
    query: str = Field(min_length=2, max_length=300)
    limit: int = Field(default=50, ge=1, le=500)


class RoleBody(BaseModel):
    role: Role


class PeerBody(BaseModel):
    address: str = Field(pattern=r"^[A-Za-z0-9.\-\[\]:]+:\d{1,5}$")
