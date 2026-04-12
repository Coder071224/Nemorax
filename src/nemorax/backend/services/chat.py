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

_FOLLOW_UP_HISTORY_WINDOW = 6
_NEMSU_TOPIC_KEYWORDS = {
    "nemsu",
    "northeastern mindanao state university",
    "besc",
    "bukidnon external studies center",
    "sspc",
    "surigao del sur polytechnic college",
    "sspsc",
    "surigao del sur polytechnic state college",
    "sdssu",
    "surigao del sur state university",
    "bislig",
    "cantilan",
    "lianga",
    "marihatag",
    "san miguel",
    "tagbina",
    "barobo",
    "lanuza",
    "main campus",
    "campus",
    "cite",
    "college of information technology education",
    "cbm",
    "college of business and management",
    "cas",
    "college of arts and sciences",
    "coed",
    "college of education",
    "coe",
    "college of engineering",
    "cag",
    "college of agriculture",
    "cthm",
    "college of tourism and hospitality management",
    "cjc",
    "college of justice and criminology",
    "con",
    "college of nursing",
    "cp",
    "college of pharmacy",
    "president",
    "vice president",
    "vp",
    "dean",
    "director",
    "registrar",
    "office",
    "offices",
    "chancellor",
    "faculty",
    "professor",
    "instructor",
    "staff",
    "admin",
    "administrator",
    "officer",
    "coordinator",
    "enrollment",
    "admissions",
    "admission",
    "tuition",
    "scholarship",
    "program",
    "course",
    "curriculum",
    "subject",
    "grade",
    "thesis",
    "research",
    "extension",
    "accreditation",
    "board",
    "exam",
    "requirement",
    "graduate",
    "undergraduate",
    "masteral",
    "doctoral",
    "year",
    "date",
    "when",
    "since",
    "until",
    "how long",
    "founded",
    "established",
    "history",
    "historical",
    "formerly",
    "before",
    "previous",
    "old name",
    "used to",
    "alias",
    "also known",
    "their",
    "its",
    "same",
    "about",
    "what about",
    "and the",
    "also",
    "more",
    "tell me more",
}

_TOPIC_TOKEN_KEYWORDS = {item for item in _NEMSU_TOPIC_KEYWORDS if " " not in item}
_TOPIC_PHRASE_KEYWORDS = {item for item in _NEMSU_TOPIC_KEYWORDS if " " in item}


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


def _normalize_topic_message(user_message: str) -> str:
    return re.sub(r"[^\w\s]", " ", (user_message or "").lower()).strip()


def _history_to_dicts(messages: Sequence[MessageSchema]) -> list[dict[str, str]]:
    return [{"role": message.role, "content": message.content} for message in messages if message.content]


def _build_rejection_reply(conversation_history: Sequence[MessageSchema]) -> str:
    if conversation_history:
        return (
            "I'm not sure I caught that in the context of our conversation. "
            "Could you clarify what you'd like to know about NEMSU?"
        )
    return (
        "I can only assist with inquiries about NEMSU "
        "(Northeastern Mindanao State University). "
        "You can ask me about programs, campuses, administration, "
        "history, enrollment, and more."
    )


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

    def _conversation_window(self, request: ChatRequest) -> list[MessageSchema]:
        non_empty_messages = [message for message in request.messages if message.content]
        trimmed_request_messages = non_empty_messages[-_FOLLOW_UP_HISTORY_WINDOW:]
        if len(trimmed_request_messages) > 1 or not request.user_id:
            return trimmed_request_messages

        stored_messages = self._history.recent_messages(
            request.session_id,
            request.user_id,
            limit=_FOLLOW_UP_HISTORY_WINDOW,
        )
        combined = [*stored_messages, *trimmed_request_messages]
        return [message for message in combined if message.content][- _FOLLOW_UP_HISTORY_WINDOW :]

    def _is_school_related(self, user_message: str, conversation_history: Sequence[MessageSchema]) -> bool:
        if len(conversation_history) > 0 and len(user_message.strip().split()) < 10:
            return True

        normalized = _normalize_topic_message(user_message)
        tokens = set(normalized.split())
        token_variants = set(tokens)
        token_variants.update(token[:-1] for token in tokens if token.endswith("s") and len(token) > 3)
        if token_variants & _TOPIC_TOKEN_KEYWORDS:
            return True
        return any(phrase in normalized for phrase in _TOPIC_PHRASE_KEYWORDS)

    def _provider_messages(self, messages: Sequence[MessageSchema]) -> list[LLMMessage]:
        trimmed_messages = [message for message in messages if message.content][-self._settings.llm.message_window :]
        latest_user_message = _extract_last_user_message(trimmed_messages)
        history_messages = trimmed_messages[:-1] if trimmed_messages else []
        prompt = self._prompt_service.get_system_prompt_for_query(
            latest_user_message,
            conversation_history=_history_to_dicts(history_messages[-_FOLLOW_UP_HISTORY_WINDOW:]),
        )
        provider_messages = [LLMMessage(role="system", content=prompt)]
        provider_messages.extend(LLMMessage(role=message.role, content=message.content) for message in history_messages)
        if latest_user_message:
            provider_messages.append(LLMMessage(role="user", content=latest_user_message))
        return provider_messages

    async def chat(self, request: ChatRequest) -> ChatResponse:
        conversation_window = self._conversation_window(request)
        latest_user_message = _extract_last_user_message(conversation_window)
        history_messages = conversation_window[:-1] if conversation_window else []

        if not self._is_school_related(latest_user_message, history_messages):
            reply = _build_rejection_reply(history_messages)
        else:
            completion = await self._provider.chat(self._provider_messages(conversation_window))
            reply = clean_nemis_reply(completion.content)

        if request.user_id:
            try:
                self._history.append_messages(
                    request.session_id,
                    latest_user_message,
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
