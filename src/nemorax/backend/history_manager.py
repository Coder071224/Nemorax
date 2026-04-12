"""Compatibility wrapper around the history service."""

from __future__ import annotations

from nemorax.backend.core.errors import NotFoundError
from nemorax.backend.runtime import get_runtime_services
from nemorax.backend.schemas import ConversationRecord, HistoryListItem


def create_conversation(session_id: str, user_id: str, title: str = "New Chat") -> ConversationRecord:
    return get_runtime_services().history_service.create_conversation(session_id, user_id, title)


def append_messages(session_id: str, user_text: str, assistant_text: str, user_id: str) -> ConversationRecord:
    return get_runtime_services().history_service.append_messages(session_id, user_text, assistant_text, user_id)


def list_conversations(user_id: str) -> list[HistoryListItem]:
    return get_runtime_services().history_service.list_conversations(user_id)


def get_conversation(session_id: str, user_id: str) -> ConversationRecord | None:
    try:
        return get_runtime_services().history_service.get_conversation(session_id, user_id)
    except NotFoundError:
        return None


def delete_conversation(session_id: str, user_id: str) -> bool:
    return get_runtime_services().history_service.delete_conversation(session_id, user_id)
