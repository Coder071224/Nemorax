from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import uuid

from nemorax.frontend import api_client
from nemorax.frontend.time_utils import parse_backend_datetime, ph_now

_HISTORY_LIMIT = 10


def _naive_now() -> datetime:
    return ph_now()


def _has_text(value: str) -> bool:
    return bool(value.strip())


@dataclass
class Message:
    role: str
    content: str
    timestamp: datetime = field(default_factory=_naive_now)


@dataclass
class Conversation:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    title: str = "New Chat"
    messages: list[Message] = field(default_factory=list)
    created_at: datetime = field(default_factory=_naive_now)
    updated_at: datetime = field(default_factory=_naive_now)
    is_placeholder: bool = False


class HistoryService:
    def __init__(self, user_id: str | None = None) -> None:
        self.user_id = user_id
        self.conversations: list[Conversation] = []
        self.current_conversation: Conversation | None = None

        if user_id:
            self._load_from_backend()

    def _load_from_backend(self) -> None:
        if not self.user_id:
            return

        self.conversations = []
        items = api_client.list_history(self.user_id)

        for item in items:
            if not isinstance(item, dict):
                continue

            session_id = item.get("session_id")
            if not isinstance(session_id, str) or not session_id.strip():
                continue

            self.conversations.append(
                Conversation(
                    id=session_id,
                    title=str(item.get("title", "New Chat")) or "New Chat",
                    created_at=parse_backend_datetime(item.get("created_at")),
                    updated_at=parse_backend_datetime(item.get("updated_at")),
                    is_placeholder=False,
                )
            )

        self._enforce_limit()

    def reload(self, user_id: str | None) -> None:
        """Reload persisted history for a new user."""
        self.user_id = user_id
        self.conversations = []
        self.current_conversation = None

        if user_id:
            self._load_from_backend()

    def _conversation_has_content(self, conversation: Conversation | None) -> bool:
        if conversation is None:
            return False

        return any(_has_text(message.content) for message in conversation.messages)

    def _conversation_title_from_text(self, text: str) -> str:
        trimmed = text.strip().replace("\n", " ")
        if not trimmed:
            return "New Chat"
        return f"{trimmed[:40]}..." if len(trimmed) > 40 else trimmed

    def _ensure_current_listed(self) -> None:
        """
        Add the current conversation to the visible list only after it has
        at least one real message and is no longer a placeholder.
        """
        current = self.current_conversation
        if current is None:
            return
        if current.is_placeholder:
            return
        if not self._conversation_has_content(current):
            return
        if any(conversation.id == current.id for conversation in self.conversations):
            return

        self.conversations.insert(0, current)
        self._enforce_limit()

    def _sorted_conversations(self) -> list[Conversation]:
        return sorted(
            self.conversations,
            key=lambda conversation: conversation.updated_at,
            reverse=True,
        )

    def _enforce_limit(self) -> None:
        self.conversations = self._sorted_conversations()[:_HISTORY_LIMIT]

    def _hydrate(self, conversation: Conversation) -> None:
        if not self.user_id:
            return

        record = api_client.load_conversation(conversation.id, self.user_id)
        if not isinstance(record, dict):
            return

        conversation.title = str(record.get("title", conversation.title)) or "New Chat"
        conversation.created_at = parse_backend_datetime(record.get("created_at"))
        conversation.updated_at = parse_backend_datetime(record.get("updated_at"))
        conversation.messages = [
            Message(
                role=str(message.get("role", "")),
                content=str(message.get("content", "")),
                timestamp=parse_backend_datetime(message.get("timestamp")),
            )
            for message in record.get("messages", [])
            if isinstance(message, dict) and _has_text(str(message.get("content", "")))
        ]
        conversation.is_placeholder = False

        if conversation.messages:
            conversation.updated_at = conversation.messages[-1].timestamp

    def new_conversation(self) -> Conversation:
        """
        Start a fresh unsaved conversation for the main chat area.
        This stays as a placeholder until the first real user message is sent.
        """
        conversation = Conversation(
            id=str(uuid.uuid4()),
            title="New Chat",
            is_placeholder=True,
        )
        self.current_conversation = conversation
        return conversation

    def activate_most_recent_conversation(self) -> Conversation | None:
        ordered = self._sorted_conversations()
        if not ordered:
            return None

        return self.switch_conversation(ordered[0].id)

    def switch_conversation(self, conversation_id: str) -> Conversation | None:
        """
        If a blank placeholder is currently open, switching to a persisted
        conversation replaces that placeholder as the current conversation.
        """
        for conversation in self.conversations:
            if conversation.id != conversation_id:
                continue

            if not conversation.messages and self.user_id:
                self._hydrate(conversation)

            conversation.is_placeholder = False
            self.current_conversation = conversation
            return conversation

        return None

    def get_all_conversations(self) -> list[Conversation]:
        """
        Sidebar behavior:
        - persisted conversations are always shown
        - if the current chat is a blank placeholder, show it at the top
        - if the current chat becomes real, include it once as a normal item
        """
        ordered = self._sorted_conversations()[:_HISTORY_LIMIT]
        current = self.current_conversation

        if current is None:
            return ordered

        if current.is_placeholder and not self._conversation_has_content(current):
            return [current, *ordered]

        if self._conversation_has_content(current) and not any(
            conversation.id == current.id for conversation in ordered
        ):
            return [current, *ordered][: _HISTORY_LIMIT]

        return ordered

    def add_message(self, role: str, content: str) -> Message:
        if self.current_conversation is None:
            self.new_conversation()

        assert self.current_conversation is not None

        message = Message(role=role, content=content, timestamp=_naive_now())
        self.current_conversation.messages.append(message)
        self.current_conversation.updated_at = message.timestamp

        if role == "user":
            if self.current_conversation.is_placeholder:
                self.current_conversation.is_placeholder = False

            if self.current_conversation.title == "New Chat":
                self.current_conversation.title = self._conversation_title_from_text(content)

        self._ensure_current_listed()
        return message

    def delete_conversation(self, conversation_id: str) -> bool:
        before_count = len(self.conversations)
        self.conversations = [
            conversation
            for conversation in self.conversations
            if conversation.id != conversation_id
        ]

        deleted = len(self.conversations) != before_count
        if self.current_conversation is not None and self.current_conversation.id == conversation_id:
            self.current_conversation = None
            deleted = True

        if deleted:
            self._enforce_limit()
        return deleted

    def get_chat_messages(self) -> list[dict[str, str]]:
        current = self.current_conversation
        if current is None:
            return []

        return [
            {"role": message.role, "content": message.content}
            for message in current.messages
            if _has_text(message.content)
        ]

    def get_api_messages(self) -> list[dict[str, str]]:
        return self.get_chat_messages()

    def current_is_empty(self) -> bool:
        return not self._conversation_has_content(self.current_conversation)

