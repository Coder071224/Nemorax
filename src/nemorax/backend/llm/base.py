"""Abstract interfaces for model providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from .models import ChatCompletionResult, LLMMessage, ProviderStatus


class ChatProvider(ABC):
    """Common interface for any chat-capable model backend."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the normalized provider name."""

    @property
    @abstractmethod
    def model(self) -> str:
        """Return the configured model identifier."""

    @property
    @abstractmethod
    def base_url(self) -> str:
        """Return the configured provider endpoint base URL."""

    @property
    @abstractmethod
    def provider_label(self) -> str:
        """Return the provider label for human-readable diagnostics."""

    @abstractmethod
    async def chat(self, messages: Sequence[LLMMessage]) -> ChatCompletionResult:
        """Generate a chat completion for the supplied conversation."""

    @abstractmethod
    async def health(self) -> ProviderStatus:
        """Return a health snapshot for the provider."""
