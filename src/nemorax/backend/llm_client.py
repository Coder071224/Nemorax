"""Compatibility wrapper around the configured model provider."""

from __future__ import annotations

from collections.abc import Sequence

from nemorax.backend.config import settings
from nemorax.backend.llm.models import LLMMessage
from nemorax.backend.runtime import get_runtime_services


LLM_MODEL = settings.llm.model


async def is_available() -> bool:
    status = await get_runtime_services().llm_provider.health()
    return bool(status.available)


async def chat(messages: Sequence[dict[str, str]]) -> str:
    provider = get_runtime_services().llm_provider
    system_prompt = get_runtime_services().prompt_service.get_system_prompt()
    normalized_messages = [LLMMessage(role="system", content=system_prompt)]
    normalized_messages.extend(
        LLMMessage(role=str(item.get("role", "")), content=str(item.get("content", "")))
        for item in messages
        if str(item.get("content", "")).strip()
    )
    completion = await provider.chat(normalized_messages)
    return completion.content
