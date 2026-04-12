"""File-backed conversation history repository."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any

from nemorax.backend.core.settings import PathSettings
from nemorax.backend.repositories.json_store import read_json_object, write_json_atomic
from nemorax.backend.schemas import ConversationRecord, HistoryListItem


_HISTORY_LIMIT = 10


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        return datetime.min.replace(tzinfo=timezone.utc)

    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)

    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _conversation_sort_key(conversation: dict[str, Any]) -> datetime:
    updated_at = _parse_timestamp(conversation.get("updated_at"))
    if updated_at != datetime.min.replace(tzinfo=timezone.utc):
        return updated_at
    return _parse_timestamp(conversation.get("created_at"))


def _normalize_message(message: Any) -> dict[str, str] | None:
    if not isinstance(message, dict):
        return None

    role = str(message.get("role", "")).strip().lower()
    content = str(message.get("content", "")).strip()
    timestamp = str(message.get("timestamp", "")).strip() or _now_iso()
    if role not in {"user", "assistant", "system"} or not content:
        return None

    return {
        "timestamp": timestamp,
        "role": role,
        "content": content,
    }


def _normalize_conversation(conversation: Any, *, user_id: str) -> dict[str, Any] | None:
    if not isinstance(conversation, dict):
        return None

    session_id = str(conversation.get("session_id", "")).strip()
    if not session_id:
        return None

    created_at = str(conversation.get("created_at", "")).strip() or _now_iso()
    updated_at = str(conversation.get("updated_at", "")).strip() or created_at
    title = str(conversation.get("title", "New Chat")).strip() or "New Chat"
    raw_messages = conversation.get("messages", [])
    messages = []
    if isinstance(raw_messages, list):
        for item in raw_messages:
            normalized = _normalize_message(item)
            if normalized is not None:
                messages.append(normalized)

    return {
        "session_id": session_id,
        "title": title,
        "created_at": created_at,
        "updated_at": updated_at,
        "messages": messages,
        "user_id": str(conversation.get("user_id", user_id)).strip() or user_id,
    }


class HistoryRepository:
    def __init__(self, paths: PathSettings) -> None:
        self._history_dir = paths.history_dir
        self._lock = RLock()

    def _path(self, user_id: str) -> Path:
        return self._history_dir / f"{user_id}.json"

    def _blank_store(self, user_id: str) -> dict[str, Any]:
        return {"user_id": user_id, "conversations": []}

    def _blank_conversation(self, session_id: str, user_id: str) -> dict[str, Any]:
        now = _now_iso()
        return {
            "session_id": session_id,
            "title": "New Chat",
            "created_at": now,
            "updated_at": now,
            "messages": [],
            "user_id": user_id,
        }

    def _load_store(self, user_id: str) -> dict[str, Any]:
        payload = read_json_object(self._path(user_id))
        if payload is None:
            return self._blank_store(user_id)

        conversations: list[dict[str, Any]] = []
        raw_conversations = payload.get("conversations", [])
        if isinstance(raw_conversations, list):
            for item in raw_conversations:
                normalized = _normalize_conversation(item, user_id=user_id)
                if normalized is not None:
                    conversations.append(normalized)

        updated_at = payload.get("updated_at")
        store: dict[str, Any] = {
            "user_id": str(payload.get("user_id", user_id)).strip() or user_id,
            "conversations": conversations,
        }
        if isinstance(updated_at, str) and updated_at.strip():
            store["updated_at"] = updated_at.strip()
        return store

    def _save_store(self, user_id: str, store: dict[str, Any], *, touch: bool = False) -> None:
        if touch:
            store["updated_at"] = _now_iso()
        write_json_atomic(self._path(user_id), store)

    @staticmethod
    def _find_conversation(store: dict[str, Any], session_id: str) -> dict[str, Any] | None:
        conversations = store.get("conversations", [])
        if not isinstance(conversations, list):
            return None

        for conversation in conversations:
            if isinstance(conversation, dict) and conversation.get("session_id") == session_id:
                return conversation
        return None

    @staticmethod
    def _append_message(conversation: dict[str, Any], *, role: str, content: str, timestamp: str) -> None:
        messages = conversation.setdefault("messages", [])
        if not isinstance(messages, list):
            conversation["messages"] = messages = []
        messages.append({"timestamp": timestamp, "role": role, "content": content})

    @staticmethod
    def _conversation_has_content(conversation: dict[str, Any]) -> bool:
        messages = conversation.get("messages", [])
        if not isinstance(messages, list):
            return False
        return any(isinstance(message, dict) and str(message.get("content", "")).strip() for message in messages)

    @staticmethod
    def _record_from_conversation(conversation: dict[str, Any]) -> ConversationRecord:
        return ConversationRecord(**conversation)

    def _prune_oldest(self, store: dict[str, Any]) -> None:
        conversations = store.get("conversations", [])
        if not isinstance(conversations, list):
            return

        while len(conversations) >= _HISTORY_LIMIT:
            oldest = min(
                (item for item in conversations if isinstance(item, dict)),
                key=_conversation_sort_key,
                default=None,
            )
            if oldest is None:
                return
            conversations.remove(oldest)

    def create_conversation(self, session_id: str, user_id: str, title: str = "New Chat") -> ConversationRecord:
        with self._lock:
            store = self._load_store(user_id)
            existing = self._find_conversation(store, session_id)
            if existing is not None:
                return self._record_from_conversation(existing)

            self._prune_oldest(store)
            conversation = self._blank_conversation(session_id, user_id)
            conversation["title"] = title.strip() or "New Chat"
            store["conversations"].append(conversation)
            self._save_store(user_id, store, touch=True)
            return self._record_from_conversation(conversation)

    def append_messages(self, session_id: str, user_text: str, assistant_text: str, user_id: str) -> ConversationRecord:
        clean_user_text = user_text.strip()
        clean_assistant_text = assistant_text.strip()

        with self._lock:
            store = self._load_store(user_id)
            conversation = self._find_conversation(store, session_id)
            if conversation is None:
                self._prune_oldest(store)
                conversation = self._blank_conversation(session_id, user_id)
                store["conversations"].append(conversation)

            if not clean_user_text and not clean_assistant_text:
                return self._record_from_conversation(conversation)

            now = _now_iso()
            if conversation.get("title") == "New Chat" and clean_user_text:
                trimmed = clean_user_text.replace("\n", " ")
                conversation["title"] = f"{trimmed[:40]}..." if len(trimmed) > 40 else trimmed or "New Chat"

            if clean_user_text:
                self._append_message(conversation, role="user", content=clean_user_text, timestamp=now)
            if clean_assistant_text:
                self._append_message(conversation, role="assistant", content=clean_assistant_text, timestamp=now)

            conversation["updated_at"] = now
            conversation["user_id"] = user_id
            self._save_store(user_id, store, touch=True)
            return self._record_from_conversation(conversation)

    def list_conversations(self, user_id: str) -> list[HistoryListItem]:
        with self._lock:
            store = self._load_store(user_id)

        items: list[HistoryListItem] = []
        conversations = store.get("conversations", [])
        if not isinstance(conversations, list):
            return items

        for conversation in conversations:
            if not isinstance(conversation, dict) or not self._conversation_has_content(conversation):
                continue

            messages = conversation.get("messages", [])
            message_count = len(messages) if isinstance(messages, list) else 0
            items.append(
                HistoryListItem(
                    session_id=str(conversation.get("session_id", "")),
                    title=str(conversation.get("title", "New Chat")) or "New Chat",
                    created_at=conversation.get("created_at", _now_iso()),
                    updated_at=conversation.get("updated_at", _now_iso()),
                    message_count=message_count,
                )
            )

        items.sort(key=lambda item: item.updated_at, reverse=True)
        return items[:_HISTORY_LIMIT]

    def get_conversation(self, session_id: str, user_id: str) -> ConversationRecord | None:
        with self._lock:
            store = self._load_store(user_id)
            conversation = self._find_conversation(store, session_id)
            if conversation is None:
                return None
            return self._record_from_conversation(conversation)

    def delete_conversation(self, session_id: str, user_id: str) -> bool:
        with self._lock:
            store = self._load_store(user_id)
            conversations = store.get("conversations", [])
            if not isinstance(conversations, list):
                return False

            filtered = [
                item
                for item in conversations
                if not isinstance(item, dict) or item.get("session_id") != session_id
            ]
            if len(filtered) == len(conversations):
                return False

            store["conversations"] = filtered
            self._save_store(user_id, store, touch=True)
            return True
