from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

ActionName = StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,31}$", min_length=1, max_length=32)


class ToolError(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None


class ActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Annotated[str, ActionName]
    arguments: dict[str, Any] = Field(default_factory=dict)
    confirmation_phrase: str | None = Field(default=None, max_length=120)


class ConfirmationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=8, max_length=256)
    confirmation_phrase: str | None = Field(default=None, max_length=120)


class ActionResponse(BaseModel):
    ok: bool
    action: str
    result: dict[str, Any] | None = None
    error: ToolError | None = None


class PendingConfirmation(BaseModel):
    request_id: str
    token: str
    action: str
    arguments: dict[str, Any]
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime
    risk: Literal["low", "medium", "high"]
    requires_confirmation: bool = True

    @property
    def is_expired(self) -> bool:
        return datetime.now(UTC) > self.expires_at
