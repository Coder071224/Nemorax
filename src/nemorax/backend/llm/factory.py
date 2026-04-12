"""Factory for constructing the configured model provider."""

from __future__ import annotations

from nemorax.backend.core.errors import ConfigurationError
from nemorax.backend.core.settings import LLMSettings
from nemorax.backend.llm.base import ChatProvider
from nemorax.backend.llm.providers.openai_compatible import OpenAICompatibleChatProvider


def build_provider(settings: LLMSettings) -> ChatProvider:
    if settings.provider == "groq":
        return OpenAICompatibleChatProvider(settings, provider_name="groq")
    if settings.provider == "openai_compatible":
        return OpenAICompatibleChatProvider(settings, provider_name="openai_compatible")
    raise ConfigurationError(f"Unsupported LLM_PROVIDER value: {settings.provider!r}")
