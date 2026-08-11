"""Request-/Response-Schemas der schlanken API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

PermissionMode = Literal[
    "default", "acceptEdits", "plan", "bypassPermissions", "dontAsk", "auto"
]


class OneShotRequest(BaseModel):
    prompt: str
    workspace: str | None = Field(
        default=None,
        description="Unter-Verzeichnis in WORKSPACES_DIR; wird bei Bedarf angelegt.",
    )
    allowed_tools: list[str] | None = None
    disallowed_tools: list[str] | None = None
    permission_mode: PermissionMode | None = None
    model: str | None = None
    system_prompt: str | None = None
    max_turns: int | None = None
    stream: bool = False


class Usage(BaseModel):
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_input_tokens: int | None = None
    cache_creation_input_tokens: int | None = None


class OneShotResponse(BaseModel):
    result: str
    session_id: str | None = None
    is_error: bool = False
    num_turns: int | None = None
    duration_ms: int | None = None
    total_cost_usd: float | None = None
    usage: dict[str, Any] | None = None


class CreateSessionRequest(BaseModel):
    workspace: str | None = None
    git_repo: str | None = Field(default=None, description="Optionales Repo zum Klonen.")
    git_ref: str | None = None
    system_prompt: str | None = None
    allowed_tools: list[str] | None = None
    disallowed_tools: list[str] | None = None
    permission_mode: PermissionMode | None = None
    model: str | None = None
    max_turns: int | None = None


class CreateSessionResponse(BaseModel):
    session_id: str
    workspace: str


class MessageRequest(BaseModel):
    prompt: str


class SessionInfo(BaseModel):
    session_id: str
    workspace: str
    status: Literal["idle", "busy", "closed"]
    created_at: float
    last_active: float
    num_messages: int
    claude_session_id: str | None = None


class ErrorResponse(BaseModel):
    detail: str
