"""Shared LLM-facing dataclasses."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class LLMMessage:
    role: str
    content: str


@dataclass(frozen=True, slots=True)
class ChatCompletionResult:
    provider: str
    model: str
    content: str
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProviderStatus:
    name: str
    label: str
    model: str
    base_url: str
    available: bool
    configured: bool = True
    detail: str | None = None
