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
    prompt_payload = get_runtime_services().prompt_service.build_prompt_payload(None)
    normalized_messages = [LLMMessage(role="system", content=str(prompt_payload["system_prompt"]))]
    retrieval_message = str(prompt_payload.get("retrieval_message") or "").strip()
    if retrieval_message:
        normalized_messages.append(LLMMessage(role="assistant", content=retrieval_message))
    normalized_messages.extend(
        LLMMessage(role=str(item.get("role", "")), content=str(item.get("content", "")))
        for item in messages
        if str(item.get("content", "")).strip()
    )
    completion = await provider.chat(normalized_messages)
    return completion.content
