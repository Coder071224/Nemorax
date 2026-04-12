"""Conversation history service."""

from __future__ import annotations

from nemorax.backend.core.errors import NotFoundError
from nemorax.backend.repositories.history import HistoryRepository
from nemorax.backend.schemas import ConversationRecord, HistoryListItem


class HistoryService:
    def __init__(self, history_repository: HistoryRepository) -> None:
        self._history = history_repository

    def create_conversation(self, session_id: str, user_id: str, title: str = "New Chat") -> ConversationRecord:
        return self._history.create_conversation(session_id, user_id, title)

    def append_messages(self, session_id: str, user_text: str, assistant_text: str, user_id: str) -> ConversationRecord:
        return self._history.append_messages(session_id, user_text, assistant_text, user_id)

    def list_conversations(self, user_id: str) -> list[HistoryListItem]:
        return self._history.list_conversations(user_id)

    def get_conversation(self, session_id: str, user_id: str) -> ConversationRecord:
        record = self._history.get_conversation(session_id, user_id)
        if record is None:
            raise NotFoundError("Conversation not found")
        return record

    def delete_conversation(self, session_id: str, user_id: str) -> bool:
        return self._history.delete_conversation(session_id, user_id)
