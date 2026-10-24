"""Pydantic request/response models for the gateway REST API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CredentialType = Literal["none", "bearer", "header"]

#: Roles the gateway understands. The mapping to concrete permissions lives in
#: ``config/permissions.yaml``.
RoleName = Literal["admin", "member", "viewer"]

#: Minimum length for a password set by an administrator through the reset
#: endpoint. Passwords created through the normal sign-up flow keep the
#: lower bound of :class:`UserCreate`.
MANAGED_PASSWORD_MIN_LENGTH = 12


class RoleView(BaseModel):
    name: str


class UserView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    display_name: str
    is_active: bool
    roles: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    created_at: datetime


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=200)

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        value = value.strip().lower()
        if "@" not in value or value.startswith("@") or value.endswith("@"):
            raise ValueError("invalid email address")
        return value


class LoginResponse(BaseModel):
    user: UserView
    csrf_token: str


class DemoPersonaView(BaseModel):
    """One fixed assessment identity offered by the demo entry screen."""

    id: str
    role: str
    email: str
    display_name: str
    title: str
    summary: str
    capabilities: list[str]


class DemoConfigView(BaseModel):
    """Public demo-mode metadata. Contains no credentials."""

    enabled: bool
    personas: list[DemoPersonaView] = Field(default_factory=list)
    deployment: str = "development"


class DemoSessionRequest(BaseModel):
    """Body of the demo sign-in endpoint.

    The persona is validated against a fixed allowlist; a role name here is
    rejected rather than mapped.
    """

    persona: str = Field(min_length=1, max_length=32)


class UserCreate(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    display_name: str = Field(default="", max_length=128)
    password: str = Field(min_length=8, max_length=200)
    roles: list[RoleName] = Field(default_factory=lambda: ["member"])

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        value = value.strip().lower()
        if "@" not in value or value.startswith("@") or value.endswith("@"):
            raise ValueError("invalid email address")
        return value


class UserUpdate(BaseModel):
    display_name: str | None = Field(None, min_length=1, max_length=128)
    is_active: bool | None = None
    roles: list[RoleName] | None = None


class UserPasswordSet(BaseModel):
    """Body of the administrator-only password reset endpoint."""

    password: str = Field(
        min_length=MANAGED_PASSWORD_MIN_LENGTH,
        max_length=200,
        description="New plaintext password. It is hashed before storage.",
    )


class ServerCreate(BaseModel):
    server_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(None, max_length=2000)
    url: str = Field(min_length=1, max_length=512)
    health_url: str | None = Field(None, max_length=512)
    enabled: bool = True
    credential_type: CredentialType = "none"
    credential: str | None = Field(None, max_length=4000)
    credential_header: str | None = Field(None, max_length=64)

    @model_validator(mode="after")
    def _credential_fields(self) -> "ServerCreate":
        if self.credential_type == "none":
            return self
        if not self.credential:
            raise ValueError("credential is required for the selected credential_type")
        if self.credential_type == "header" and not self.credential_header:
            raise ValueError("credential_header is required for header credentials")
        return self


class ServerUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=128)
    description: str | None = Field(None, max_length=2000)
    url: str | None = Field(None, min_length=1, max_length=512)
    health_url: str | None = Field(None, max_length=512)
    enabled: bool | None = None
    credential_type: CredentialType | None = None
    credential: str | None = Field(None, max_length=4000)
    credential_header: str | None = Field(None, max_length=64)
    clear_credential: bool = False


class ServerView(BaseModel):
    server_id: str
    name: str
    description: str | None = None
    transport: str
    url: str | None = None
    health_url: str | None = None
    enabled: bool
    status: str
    has_credential: bool
    credential_type: str
    tool_count: int
    last_error: str | None = None
    last_checked_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ToolView(BaseModel):
    name: str
    server_id: str
    upstream_tool: str
    description: str | None = None
    input_schema: dict[str, Any]
    permitted: bool = True


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    expires_in_days: int | None = Field(None, ge=1, le=3650)
    user_id: int | None = Field(None, ge=1, description="Admin-only: create for another user")


class ApiKeyView(BaseModel):
    id: int
    name: str
    prefix: str
    user_id: int
    created_at: datetime
    expires_at: datetime | None = None
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None
    active: bool


class ApiKeyCreated(ApiKeyView):
    api_key: str = Field(description="Plaintext key, shown only once")


class AuditView(BaseModel):
    id: int
    created_at: datetime
    user_id: int | None = None
    user_email: str | None = None
    api_key_id: int | None = None
    server_id: str
    public_tool_name: str | None = None
    upstream_tool_name: str | None = None
    status: str
    error_code: str | None = None
    latency_ms: float | None = None


class AuditPage(BaseModel):
    items: list[AuditView]
    page: int
    per_page: int
    total: int
    has_more: bool


class Overview(BaseModel):
    upstreams_enabled: int
    upstreams_total: int
    tools_total: int
    tools_permitted: int
    servers: list[ServerView]
    recent_activity: list[AuditView]


class Message(BaseModel):
    message: str
