"""File-backed user repository."""

from __future__ import annotations

from pathlib import Path
from threading import RLock
from typing import Any

from nemorax.backend.core.settings import PathSettings
from nemorax.backend.repositories.json_store import JsonObject, read_json_object, write_json_atomic


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
    def __init__(self, paths: PathSettings) -> None:
        self._users_dir = paths.users_dir
        self._lock = RLock()

    def _user_path(self, user_id: str) -> Path:
        return self._users_dir / f"{user_id}.json"

    def _iter_user_files(self) -> list[Path]:
        self._users_dir.mkdir(parents=True, exist_ok=True)
        return sorted(self._users_dir.glob("*.json"))

    def get_by_id(self, user_id: str) -> UserRecord | None:
        with self._lock:
            return read_json_object(self._user_path(user_id))

    def find_by_email(self, email: str) -> tuple[UserRecord | None, Path | None]:
        target = normalize_email(email)
        with self._lock:
            for path in self._iter_user_files():
                user = read_json_object(path)
                if user is None:
                    continue
                if normalize_email(str(user.get("email", ""))) == target:
                    return user, path
        return None, None

    def save(self, user: JsonObject) -> None:
        user_id = str(user.get("user_id", "")).strip()
        if not user_id:
            raise ValueError("user_id is required to save a user record.")
        with self._lock:
            write_json_atomic(self._user_path(user_id), user)
