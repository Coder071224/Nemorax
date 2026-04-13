"""Supabase-backed conversation history repository."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from nemorax.backend.core.errors import PersistenceError
from nemorax.backend.repositories.supabase_client import SupabasePersistenceClient
from nemorax.backend.schemas import ConversationRecord, HistoryListItem


_HISTORY_LIMIT = 10


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_title(title: str) -> str:
    cleaned = title.strip()
    return cleaned or "New Chat"


def _title_from_user_text(text: str) -> str:
    trimmed = text.strip().replace("\n", " ")
    if not trimmed:
        return "New Chat"
    return f"{trimmed[:40]}..." if len(trimmed) > 40 else trimmed


def _message_row_to_payload(message: dict[str, Any]) -> dict[str, Any] | None:
    role = str(message.get("role", "")).strip().lower()
    content = str(message.get("content", "")).strip()
    timestamp = str(message.get("timestamp", "")).strip() or _now_iso()
    if role not in {"user", "assistant", "system"} or not content:
        return None
    return {
        "role": role,
        "content": content,
        "timestamp": timestamp,
    }


class HistoryRepository:
    def __init__(self, client: SupabasePersistenceClient) -> None:
        self._client = client

    def _session_row(self, session_id: str, user_id: str) -> dict[str, Any] | None:
        return self._client.select_one(
            "conversation_sessions",
            filters={"session_id": session_id, "user_id": user_id},
        )

    def _message_rows(self, session_id: str, user_id: str) -> list[dict[str, Any]]:
        rows = self._client.select(
            "conversation_messages",
            columns="session_id,user_id,sequence,role,content,timestamp",
            filters={"session_id": session_id, "user_id": user_id},
            order="sequence.asc",
        )
        return rows

    def _prune_oldest(self, user_id: str) -> None:
        rows = self._client.select(
            "conversation_sessions",
            columns="session_id,updated_at,created_at",
            filters={"user_id": user_id},
            order="updated_at.asc",
            limit=_HISTORY_LIMIT + 5,
        )
        if len(rows) < _HISTORY_LIMIT:
            return
        while len(rows) >= _HISTORY_LIMIT:
            oldest = rows.pop(0)
            session_id = str(oldest.get("session_id", "")).strip()
            if session_id:
                self.delete_conversation(session_id, user_id)

    def _record_from_rows(self, session: dict[str, Any], messages: list[dict[str, Any]]) -> ConversationRecord:
        session_user_id = str(session.get("user_id", "")).strip()
        normalized_messages = [
            payload
            for payload in (_message_row_to_payload(message) for message in messages)
            if payload is not None
        ]
        return ConversationRecord(
            session_id=str(session.get("session_id", "")).strip(),
            title=_normalize_title(str(session.get("title", "New Chat"))),
            created_at=str(session.get("created_at", "")).strip() or _now_iso(),
            updated_at=str(session.get("updated_at", "")).strip() or _now_iso(),
            messages=normalized_messages,
            user_id=session_user_id or None,
        )

    def create_conversation(self, session_id: str, user_id: str, title: str = "New Chat") -> ConversationRecord:
        existing = self._session_row(session_id, user_id)
        if existing is not None:
            return self._record_from_rows(existing, self._message_rows(session_id, user_id))

        self._prune_oldest(user_id)
        now = _now_iso()
        payload = {
            "session_id": session_id,
            "user_id": user_id,
            "title": _normalize_title(title),
            "created_at": now,
            "updated_at": now,
            "message_count": 0,
        }
        rows = self._client.upsert("conversation_sessions", payload, on_conflict="session_id", returning="representation")
        session = rows[0] if rows else payload
        return self._record_from_rows(session, [])

    def append_messages(self, session_id: str, user_text: str, assistant_text: str, user_id: str) -> ConversationRecord:
        clean_user_text = user_text.strip()
        clean_assistant_text = assistant_text.strip()

        existing = self._session_row(session_id, user_id)
        if existing is None:
            self._prune_oldest(user_id)

        if not clean_user_text and not clean_assistant_text:
            conversation = existing or self.create_conversation(session_id, user_id)
            return conversation

        message_timestamp = _now_iso()
        fallback_title = _title_from_user_text(clean_user_text) if clean_user_text else "New Chat"
        self._client.rpc(
            "append_conversation_messages",
            {
                "p_session_id": session_id,
                "p_user_id": user_id,
                "p_user_text": clean_user_text,
                "p_assistant_text": clean_assistant_text,
                "p_fallback_title": fallback_title,
                "p_message_timestamp": message_timestamp,
            },
        )
        session = self._session_row(session_id, user_id)
        if session is None:
            raise PersistenceError("Conversation append completed without a session record.")
        return self._record_from_rows(session, self._message_rows(session_id, user_id))

    def list_conversations(self, user_id: str) -> list[HistoryListItem]:
        rows = self._client.select(
            "conversation_sessions",
            columns="session_id,title,created_at,updated_at,message_count",
            filters={"user_id": user_id, "message_count": ("gt", 0)},
            order="updated_at.desc",
            limit=_HISTORY_LIMIT,
        )
        return [
            HistoryListItem(
                session_id=str(row.get("session_id", "")).strip(),
                title=_normalize_title(str(row.get("title", "New Chat"))),
                created_at=str(row.get("created_at", "")).strip() or _now_iso(),
                updated_at=str(row.get("updated_at", "")).strip() or _now_iso(),
                message_count=int(row.get("message_count", 0) or 0),
            )
            for row in rows
        ]

    def get_conversation(self, session_id: str, user_id: str) -> ConversationRecord | None:
        session = self._session_row(session_id, user_id)
        if session is None:
            return None
        return self._record_from_rows(session, self._message_rows(session_id, user_id))

    def delete_conversation(self, session_id: str, user_id: str) -> bool:
        deleted = self._client.delete(
            "conversation_sessions",
            filters={"session_id": session_id, "user_id": user_id},
            returning="representation",
        )
        return bool(deleted)

    def import_conversation(self, user_id: str, conversation: dict[str, Any]) -> ConversationRecord | None:
        session_id = str(conversation.get("session_id", "")).strip()
        if not session_id:
            return None

        created_at = str(conversation.get("created_at", "")).strip() or _now_iso()
        updated_at = str(conversation.get("updated_at", "")).strip() or created_at
        title = _normalize_title(str(conversation.get("title", "New Chat")))
        raw_messages = conversation.get("messages", [])
        messages: list[dict[str, Any]] = []
        if isinstance(raw_messages, list):
            for item in raw_messages:
                if not isinstance(item, dict):
                    continue
                normalized = _message_row_to_payload(item)
                if normalized is not None:
                    messages.append(normalized)

        self._client.upsert(
            "conversation_sessions",
            {
                "session_id": session_id,
                "user_id": user_id,
                "title": title,
                "created_at": created_at,
                "updated_at": updated_at,
                "message_count": len(messages),
            },
            on_conflict="session_id",
            returning="minimal",
        )
        self._client.delete(
            "conversation_messages",
            filters={"session_id": session_id, "user_id": user_id},
            returning="minimal",
        )
        if messages:
            self._client.insert(
                "conversation_messages",
                [
                    {
                        "session_id": session_id,
                        "user_id": user_id,
                        "sequence": index + 1,
                        "role": message["role"],
                        "content": message["content"],
                        "timestamp": message["timestamp"],
                    }
                    for index, message in enumerate(messages)
                ],
                returning="minimal",
            )

        session = self._session_row(session_id, user_id)
        if session is None:
            return None
        return self._record_from_rows(session, self._message_rows(session_id, user_id))
