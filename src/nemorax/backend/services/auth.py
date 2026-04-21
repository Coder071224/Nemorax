"""Account and profile business logic."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone
from typing import Any
import uuid

from nemorax.backend.core.errors import AuthenticationError, NotFoundError, ValidationError
from nemorax.backend.repositories.users import (
    UserRecord,
    UserRepository,
    normalize_answer,
    normalize_display_name,
    normalize_email,
    public_settings,
    public_user,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        260_000,
    ).hex()


def _display_name_from_email(email: str) -> str:
    local_part = email.split("@", 1)[0]
    cleaned = local_part.replace(".", " ").replace("_", " ").replace("-", " ").strip()
    return cleaned.title() or "User"


def _normalize_recovery_answers(recovery_answers: dict[str, str]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for question, answer in recovery_answers.items():
        clean_question = question.strip()
        clean_answer = normalize_answer(answer)
        if clean_question and clean_answer:
            normalized[clean_question] = clean_answer
    return normalized


class AuthService:
    def __init__(self, user_repository: UserRepository) -> None:
        self._users = user_repository

    def register_user(self, email: str, password: str, recovery_answers: dict[str, str]) -> str:
        normalized_email = normalize_email(email)
        if not normalized_email or "@" not in normalized_email:
            raise ValidationError("Please enter a valid email address.")
        if len(password) < 6:
            raise ValidationError("Password must be at least 6 characters.")

        normalized_answers = _normalize_recovery_answers(recovery_answers)
        if len(normalized_answers) < 2:
            raise ValidationError("At least 2 recovery answers are required.")

        existing_user, _ = self._users.find_by_email(normalized_email)
        if existing_user is not None:
            raise ValidationError("An account with this email already exists.")

        user_id = str(uuid.uuid4())
        salt = secrets.token_hex(16)
        now = _now()
        user: UserRecord = {
            "user_id": user_id,
            "email": normalized_email,
            "display_name": _display_name_from_email(normalized_email),
            "password_hash": _hash_password(password, salt),
            "salt": salt,
            "recovery_answers": normalized_answers,
            "created_at": now,
            "updated_at": now,
            "settings": {},
        }
        self._users.save(user)
        return "Account created successfully."

    def login_user(self, email: str, password: str) -> tuple[dict[str, Any], str]:
        user, _ = self._users.find_by_email(email)
        if user is None:
            raise AuthenticationError("Invalid email or password.")

        salt = str(user.get("salt", ""))
        password_hash = str(user.get("password_hash", ""))
        if not secrets.compare_digest(_hash_password(password, salt), password_hash):
            raise AuthenticationError("Invalid email or password.")

        return public_user(user), "Login successful."

    def get_recovery_questions(self, email: str) -> list[str]:
        user, _ = self._users.find_by_email(email)
        if user is None:
            return []

        answers = user.get("recovery_answers", {})
        return list(answers.keys()) if isinstance(answers, dict) else []

    def verify_recovery_answers(self, email: str, answers: dict[str, str]) -> str:
        user, _ = self._users.find_by_email(email)
        if user is None:
            raise NotFoundError("No account found for this email.")

        stored_answers = user.get("recovery_answers", {})
        if not isinstance(stored_answers, dict):
            raise ValidationError("Recovery answers do not match. Please try again.")

        matched_count = sum(
            1
            for question, answer in answers.items()
            if stored_answers.get(question.strip()) == normalize_answer(answer)
        )
        if matched_count < 2:
            raise ValidationError("Recovery answers do not match. Please try again.")
        return "Recovery answers verified."

    def reset_password(self, email: str, new_password: str) -> str:
        if len(new_password) < 6:
            raise ValidationError("Password must be at least 6 characters.")

        user, _ = self._users.find_by_email(email)
        if user is None:
            raise NotFoundError("Account not found.")

        salt = secrets.token_hex(16)
        user["salt"] = salt
        user["password_hash"] = _hash_password(new_password, salt)
        user["updated_at"] = _now()
        self._users.save(user)
        return "Password reset successfully."

    def get_user(self, user_id: str) -> UserRecord | None:
        return self._users.get_by_id(user_id)

    def get_public_user(self, user_id: str) -> dict[str, Any] | None:
        user = self._users.get_by_id(user_id)
        return None if user is None else public_user(user)

    def read_user_settings(self, user_id: str) -> dict[str, Any]:
        user = self._users.get_by_id(user_id)
        return {} if user is None else public_settings(user)

    def update_user_settings(self, user_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        user = self._users.get_by_id(user_id)
        if user is None:
            raise NotFoundError("User not found")

        current_settings = user.get("settings", {})
        if not isinstance(current_settings, dict):
            current_settings = {}

        changed = False
        if "theme" in updates:
            theme = updates.get("theme")
            current_theme = current_settings.get("theme")
            if isinstance(theme, str) and theme.strip():
                normalized_theme = theme.strip()
                if current_theme != normalized_theme:
                    current_settings["theme"] = normalized_theme
                    changed = True
            elif "theme" in current_settings:
                current_settings.pop("theme", None)
                changed = True

        if "show_splash" in updates:
            show_splash = updates.get("show_splash")
            current_show_splash = current_settings.get("show_splash")
            if isinstance(show_splash, bool):
                if current_show_splash is not show_splash:
                    current_settings["show_splash"] = show_splash
                    changed = True
            elif "show_splash" in current_settings:
                current_settings.pop("show_splash", None)
                changed = True

        if changed:
            user["settings"] = current_settings
            user["updated_at"] = _now()
            self._users.save(user)

        return public_settings(user)

    def update_display_name(self, user_id: str, display_name: str | None) -> dict[str, Any]:
        user = self._users.get_by_id(user_id)
        if user is None:
            raise NotFoundError("User not found")

        try:
            normalized_display_name = normalize_display_name(display_name)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc

        current_display_name = normalize_display_name(user.get("display_name"))
        if normalized_display_name != current_display_name:
            user["display_name"] = normalized_display_name
            user["updated_at"] = _now()
            self._users.save(user)

        return public_user(user)
