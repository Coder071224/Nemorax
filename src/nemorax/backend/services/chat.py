"""Neutral chat service that hides provider-specific details."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
import re
from typing import Any

from nemorax.backend.core.logging import get_logger
from nemorax.backend.core.settings import Settings
from nemorax.backend.llm.base import ChatProvider
from nemorax.backend.llm.models import LLMMessage
from nemorax.backend.schemas import ChatRequest, ChatResponse, MessageSchema
from nemorax.backend.services.history import HistoryService
from nemorax.backend.services.prompt import KnowledgeBasePromptService


logger = get_logger("nemorax.chat")


def clean_nemis_reply(text: str) -> str:
    if not text:
        return text

    cleaned = text.replace("**", "").replace("*", "")
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _extract_last_user_message(messages: Sequence[MessageSchema]) -> str:
    for message in reversed(list(messages)):
        if message.role == "user":
            return message.content.strip()
    return ""


class ChatService:
    def __init__(
        self,
        *,
        settings: Settings,
        provider: ChatProvider,
        prompt_service: KnowledgeBasePromptService,
        history_service: HistoryService,
    ) -> None:
        self._settings = settings
        self._provider = provider
        self._prompt_service = prompt_service
        self._history = history_service

    @property
    def provider(self) -> ChatProvider:
        return self._provider

    def _provider_messages(self, messages: Sequence[MessageSchema]) -> list[LLMMessage]:
        non_empty_messages = [message for message in messages if message.content]
        trimmed_messages = non_empty_messages[-self._settings.llm.message_window :]
        prompt = self._prompt_service.get_system_prompt_for_query(_extract_last_user_message(trimmed_messages))
        provider_messages = [LLMMessage(role="system", content=prompt)]
        provider_messages.extend(
            LLMMessage(role=message.role, content=message.content)
            for message in trimmed_messages
        )
        return provider_messages

    async def chat(self, request: ChatRequest) -> ChatResponse:
        completion = await self._provider.chat(self._provider_messages(request.messages))
        reply = clean_nemis_reply(completion.content)

        if request.user_id:
            try:
                self._history.append_messages(
                    request.session_id,
                    _extract_last_user_message(request.messages),
                    reply,
                    request.user_id,
                )
            except Exception as exc:
                logger.exception(
                    "Failed to persist conversation history for user_id=%s session_id=%s",
                    request.user_id,
                    request.session_id,
                    exc_info=exc,
                )

        return ChatResponse(
            session_id=request.session_id,
            reply=reply,
            timestamp=_utc_now(),
        )

    async def health(self) -> dict[str, Any]:
        provider_status = await self._provider.health()
        prompt_status = self._prompt_service.health()
        return {
            "status": "ok",
            "environment": self._settings.environment,
            "provider_name": provider_status.name,
            "provider_model": provider_status.model,
            "provider_available": provider_status.available,
            "provider": {
                "name": provider_status.name,
                "label": provider_status.label,
                "model": provider_status.model,
                "base_url": provider_status.base_url,
                "available": provider_status.available,
                "configured": provider_status.configured,
                "detail": provider_status.detail,
            },
            "knowledge_base": prompt_status,
            "model": provider_status.model,
        }
