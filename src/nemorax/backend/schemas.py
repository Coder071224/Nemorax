"""Pydantic models used by the Nemorax backend."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, RootModel, field_validator


class MessageSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str
    content: str
    timestamp: datetime | None = None

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"user", "assistant", "system"}:
            raise ValueError("role must be one of: user, assistant, system")
        return normalized

    @field_validator("content")
    @classmethod
    def normalize_content(cls, value: str) -> str:
        return value.strip()


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(..., min_length=1, description="Conversation session identifier")
    messages: list[MessageSchema] = Field(default_factory=list)
    user_id: str | None = None

    @field_validator("session_id")
    @classmethod
    def normalize_session_id(cls, value: str) -> str:
        return value.strip()

    @field_validator("user_id")
    @classmethod
    def normalize_user_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    timestamp: datetime


class ConversationRecord(BaseModel):
    session_id: str
    title: str = "New Chat"
    created_at: datetime
    updated_at: datetime
    messages: list[MessageSchema] = Field(default_factory=list)
    user_id: str | None = None


class HistoryListItem(BaseModel):
    session_id: str
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str | None = None
    rating: int | None = Field(default=None, ge=1, le=5)
    comment: str = ""
    category: str | None = None
    user_id: str | None = None

    @field_validator("comment")
    @classmethod
    def normalize_comment(cls, value: str) -> str:
        return value.strip()


class FeedbackResponse(BaseModel):
    feedback_id: str
    saved_at: datetime
    message: str = "Thank you for your feedback!"


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str
    password: str
    recovery_answers: dict[str, str]


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str
    password: str


class RecoveryQuestionsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str


class RecoveryQuestionsResponse(BaseModel):
    email: str
    questions: list[str]


class VerifyRecoveryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str
    answers: dict[str, str]


class ResetPasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str
    new_password: str


class AuthResponse(BaseModel):
    success: bool
    message: str
    user_id: str | None = None
    email: str | None = None
    display_name: str | None = None
    settings: dict[str, Any] = Field(default_factory=dict)


class UserProfileResponse(BaseModel):
    user_id: str
    email: str
    display_name: str | None = None
    settings: dict[str, Any] = Field(default_factory=dict)


class DisplayNameUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = None

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        if len(cleaned) > 30:
            raise ValueError("display_name must be at most 30 characters")
        return cleaned


class SettingsUpdateRequest(RootModel[dict[str, Any]]):
    def to_dict(self) -> dict[str, Any]:
        return dict(self.root)


class ProviderHealthResponse(BaseModel):
    name: str
    label: str
    model: str
    base_url: str
    available: bool
    configured: bool = True
    detail: str | None = None


class KnowledgeBaseHealthResponse(BaseModel):
    available: bool
    source_path: str
    detail: str | None = None


class HealthResponse(BaseModel):
    status: str
    environment: str
    provider_name: str
    provider_model: str
    provider_available: bool
    provider: ProviderHealthResponse
    knowledge_base: KnowledgeBaseHealthResponse
    model: str
