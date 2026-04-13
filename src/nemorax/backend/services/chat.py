"""Neutral chat service that hides provider-specific details."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from difflib import SequenceMatcher
import re
from typing import Any

try:
    from rapidfuzz import fuzz
except ImportError:
    class _FuzzFallback:
        @staticmethod
        def ratio(left: str, right: str) -> float:
            return SequenceMatcher(None, left, right).ratio() * 100

    fuzz = _FuzzFallback()

from nemorax.backend.core.logging import get_logger
from nemorax.backend.core.settings import Settings
from nemorax.backend.llm.base import ChatProvider
from nemorax.backend.llm.models import LLMMessage
from nemorax.backend.schemas import ChatRequest, ChatResponse, MessageSchema
from nemorax.backend.services.history import HistoryService
from nemorax.backend.services.prompt import KnowledgeBasePromptService


logger = get_logger("nemorax.chat")

_FOLLOW_UP_HISTORY_WINDOW = 6
_MIN_RETRIEVAL_EVIDENCE_SCORE = 3.0
_GREETING_PATTERN = re.compile(r"\b(hi|hello|hey|good morning|good afternoon|good evening|kumusta|musta|yo|hola)\b")
_INSTITUTION_ALIASES: dict[str, tuple[str, ...]] = {
    "nemsu": (
        "north eastern mindanao state university",
        "northeastern mindanao state university",
        "surigao del sur state university",
        "sdssu",
    ),
    "cite": (
        "college of information technology education",
        "college of it education",
        "college of information technology",
    ),
    "cbm": ("college of business and management",),
    "cas": ("college of arts and sciences",),
    "coed": ("college of education", "college of teacher education"),
    "coe": ("college of engineering", "college of engineering and technology"),
    "cag": ("college of agriculture", "agriculture and forestry programs"),
    "cthm": ("college of tourism and hospitality management",),
    "cjc": ("college of justice and criminology", "college of criminal justice education"),
    "con": ("college of nursing",),
    "cp": ("college of pharmacy",),
    "grad school": ("graduate school",),
}
_INSTITUTION_ANCHORS = {
    "nemsu",
    "north eastern mindanao state university",
    "northeastern mindanao state university",
    "sdssu",
    "besc",
    "sspc",
    "sspsc",
    "campus",
    "bislig",
    "cantilan",
    "lianga",
    "cagwait",
    "tagbina",
    "san miguel",
    "tandag",
    "cite",
    "cbm",
    "cas",
    "coed",
    "coe",
    "cag",
    "cthm",
    "cjc",
    "con",
    "cp",
}
_SCHOOL_ROLE_TERMS = {
    "dean",
    "president",
    "registrar",
    "director",
    "faculty",
    "professor",
    "office",
    "offices",
    "contact",
    "email",
    "phone",
    "admission",
    "admissions",
    "enrollment",
    "scholarship",
    "program",
    "programs",
    "course",
    "courses",
    "history",
    "official",
    "college",
    "department",
    "campus",
}
_LIGHT_FOLLOW_UP_MARKERS = {"about", "also", "and", "same", "their", "its", "there", "that", "this"}
_OUT_OF_DOMAIN_MARKERS = {
    "philippines",
    "weather",
    "recipe",
    "movie",
    "anime",
    "basketball",
    "nba",
    "president of the philippines",
    "capital of",
    "celebrity",
    "bitcoin",
    "stock",
}
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


class _DomainAssessment(dict[str, Any]):
    pass


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
            "I might be missing the NEMSU part of that. "
            "Could you rephrase it in terms of a campus, office, college, program, or school concern?"
        )
    return (
        "I can help with NEMSU-related questions like programs, campuses, colleges, offices, admissions, and history."
    )


def _build_greeting_reply() -> str:
    return (
        "Hi! I can help with NEMSU questions about campuses, colleges, programs, offices, admissions, history, and other school information."
    )


def _build_uncertain_reply(alias_hits: Sequence[str]) -> str:
    if alias_hits:
        return (
            f"I'm not fully sure yet based on my current NEMSU data. If you mean {alias_hits[0]}, "
            "try adding the campus, office, or college name and I'll narrow it down."
        )
    return (
        "I'm not fully sure yet based on my current NEMSU data. "
        "Try mentioning the campus, office, college, or program so I can narrow it down."
    )


def _is_greeting(user_message: str) -> bool:
    return bool(_GREETING_PATTERN.search((user_message or "").lower()))


def _alias_hits(normalized_query: str) -> list[str]:
    hits: list[str] = []
    tokens = normalized_query.split()
    for alias, expansions in _INSTITUTION_ALIASES.items():
        if alias in normalized_query:
            hits.append(expansions[0])
            continue
        for token in tokens:
            if len(token) < 3:
                continue
            threshold = 75 if len(alias) <= 4 else 86
            if fuzz.ratio(token, alias) >= threshold:
                hits.append(expansions[0])
                break
    deduped: list[str] = []
    seen: set[str] = set()
    for item in hits:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _normalized_query_with_aliases(user_message: str, alias_hits: Sequence[str]) -> str:
    extras = " ".join(alias_hits)
    return f"{user_message.strip()} {extras}".strip()


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

    def _assess_domain(self, user_message: str, conversation_history: Sequence[MessageSchema]) -> _DomainAssessment:
        normalized = _normalize_topic_message(user_message)
        tokens = set(normalized.split())
        alias_hits = _alias_hits(normalized)
        history_has_context = bool(conversation_history)
        score = 0.0

        if _is_greeting(user_message):
            return _DomainAssessment(
                confidence="greeting",
                score=1.0,
                normalized_query=normalized,
                alias_hits=alias_hits,
                expanded_query=user_message.strip(),
                refusal_reason="",
            )

        if any(anchor in normalized for anchor in _INSTITUTION_ANCHORS):
            score += 0.72
        if alias_hits:
            score += 0.44
        if history_has_context and len(tokens) <= 8:
            score += 0.28
        if history_has_context and tokens & _LIGHT_FOLLOW_UP_MARKERS:
            score += 0.18

        role_overlap = len(tokens & _SCHOOL_ROLE_TERMS)
        if role_overlap:
            score += min(0.32, role_overlap * 0.11)

        if any(phrase in normalized for phrase in _TOPIC_PHRASE_KEYWORDS):
            score += 0.2
        elif tokens & _TOPIC_TOKEN_KEYWORDS:
            score += 0.14

        out_of_domain_hit = next((marker for marker in _OUT_OF_DOMAIN_MARKERS if marker in normalized), "")
        if out_of_domain_hit and not (alias_hits or any(anchor in normalized for anchor in _INSTITUTION_ANCHORS)):
            score -= 0.75

        if score >= 0.9:
            confidence = "high"
        elif score >= 0.5:
            confidence = "medium"
        elif score >= 0.2:
            confidence = "low"
        else:
            confidence = "very_low"

        return _DomainAssessment(
            confidence=confidence,
            score=round(score, 3),
            normalized_query=normalized,
            alias_hits=alias_hits,
            expanded_query=_normalized_query_with_aliases(user_message, alias_hits),
            refusal_reason=(
                f"marker:{out_of_domain_hit}"
                if confidence == "very_low" and out_of_domain_hit
                else ("low_domain_confidence" if confidence == "very_low" else "")
            ),
        )

    def _provider_messages(self, messages: Sequence[MessageSchema], query_for_retrieval: str | None = None) -> list[LLMMessage]:
        trimmed_messages = [message for message in messages if message.content][-self._settings.llm.message_window :]
        latest_user_message = _extract_last_user_message(trimmed_messages)
        history_messages = trimmed_messages[:-1] if trimmed_messages else []
        prompt = self._prompt_service.get_system_prompt_for_query(
            query_for_retrieval or latest_user_message,
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
        assessment = self._assess_domain(latest_user_message, history_messages)
        retrieval_preview: dict[str, Any] = {"strategy": "skipped", "chunks": [], "context": "", "max_score": 0.0}

        if assessment["confidence"] in {"high", "medium", "low"}:
            try:
                retrieval_preview = self._prompt_service.preview_retrieval(
                    assessment["expanded_query"],
                    conversation_history=_history_to_dicts(history_messages[-_FOLLOW_UP_HISTORY_WINDOW:]),
                )
            except Exception as exc:
                logger.exception("Retrieval precheck failed for query=%r", latest_user_message, exc_info=exc)
                retrieval_preview = {"strategy": "error", "chunks": [], "context": "", "max_score": 0.0}

        has_retrieval_evidence = (
            len(retrieval_preview["chunks"]) > 0
            and float(retrieval_preview["max_score"]) >= _MIN_RETRIEVAL_EVIDENCE_SCORE
        )

        logger.info(
            (
                "Chat query analysis | raw=%r normalized=%r aliases=%s confidence=%s "
                "score=%.3f retrieval=%s retrieved=%d top_score=%.3f reason=%s"
            ),
            latest_user_message,
            assessment["normalized_query"],
            assessment["alias_hits"],
            assessment["confidence"],
            assessment["score"],
            retrieval_preview["strategy"],
            len(retrieval_preview["chunks"]),
            float(retrieval_preview["max_score"]),
            assessment["refusal_reason"],
        )

        if assessment["confidence"] == "greeting":
            reply = _build_greeting_reply()
        elif assessment["confidence"] == "very_low":
            reply = _build_rejection_reply(history_messages)
        elif not has_retrieval_evidence and not history_messages:
            reply = _build_uncertain_reply(assessment["alias_hits"])
        else:
            completion = await self._provider.chat(
                self._provider_messages(conversation_window, query_for_retrieval=assessment["expanded_query"])
            )
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
