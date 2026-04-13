"""Supabase-backed user repository."""

from __future__ import annotations

from typing import Any

from nemorax.backend.repositories.supabase_client import SupabasePersistenceClient


UserRecord = dict[str, Any]
_MAX_DISPLAY_NAME_LENGTH = 30


def normalize_email(email: str) -> str:
    return email.strip().lower()


def normalize_answer(answer: str) -> str:
    return answer.strip().lower()


def normalize_display_name(value: Any) -> str | None:
    if value is None:
        return None

    cleaned = str(value).strip()
    if not cleaned:
        return None
    if len(cleaned) > _MAX_DISPLAY_NAME_LENGTH:
        raise ValueError(f"display_name must be at most {_MAX_DISPLAY_NAME_LENGTH} characters.")
    return cleaned


def public_settings(user: UserRecord) -> dict[str, Any]:
    raw_settings = user.get("settings", {})
    if not isinstance(raw_settings, dict):
        return {}

    result: dict[str, Any] = {}
    theme = raw_settings.get("theme")
    if isinstance(theme, str) and theme.strip():
        result["theme"] = theme.strip()
    return result


def public_user(user: UserRecord) -> dict[str, Any]:
    return {
        "user_id": str(user.get("user_id", "")).strip(),
        "email": str(user.get("email", "")).strip(),
        "display_name": normalize_display_name(user.get("display_name")),
        "settings": public_settings(user),
    }


class UserRepository:
    def __init__(self, client: SupabasePersistenceClient) -> None:
        self._client = client

    @staticmethod
    def _normalize_user(user: dict[str, Any]) -> UserRecord:
        normalized = dict(user)
        normalized["email"] = normalize_email(str(user.get("email", "")))
        normalized["display_name"] = normalize_display_name(user.get("display_name"))
        settings = user.get("settings", {})
        normalized["settings"] = settings if isinstance(settings, dict) else {}
        answers = user.get("recovery_answers", {})
        normalized["recovery_answers"] = answers if isinstance(answers, dict) else {}
        return normalized

    def get_by_id(self, user_id: str) -> UserRecord | None:
        user = self._client.select_one("app_users", filters={"user_id": user_id})
        return None if user is None else self._normalize_user(user)

    def find_by_email(self, email: str) -> tuple[UserRecord | None, None]:
        user = self._client.select_one("app_users", filters={"email": normalize_email(email)})
        return (None if user is None else self._normalize_user(user), None)

    def save(self, user: UserRecord) -> None:
        user_id = str(user.get("user_id", "")).strip()
        if not user_id:
            raise ValueError("user_id is required to save a user record.")

        payload = self._normalize_user(user)
        payload["user_id"] = user_id
        self._client.upsert("app_users", payload, on_conflict="user_id", returning="minimal")
