"""Compatibility wrapper around the auth service."""

from __future__ import annotations

from typing import Any

from nemorax.backend.core.errors import AuthenticationError, NotFoundError, ValidationError
from nemorax.backend.runtime import get_runtime_services


def register_user(email: str, password: str, recovery_answers: dict[str, str]) -> tuple[bool, str]:
    try:
        message = get_runtime_services().auth_service.register_user(email, password, recovery_answers)
    except ValidationError as exc:
        return False, str(exc)
    return True, message


def login_user(email: str, password: str) -> tuple[dict[str, Any] | None, str]:
    try:
        return get_runtime_services().auth_service.login_user(email, password)
    except AuthenticationError as exc:
        return None, str(exc)


def get_recovery_questions(email: str) -> list[str]:
    return get_runtime_services().auth_service.get_recovery_questions(email)


def verify_recovery_answers(email: str, answers: dict[str, str]) -> tuple[bool, str]:
    try:
        message = get_runtime_services().auth_service.verify_recovery_answers(email, answers)
    except (NotFoundError, ValidationError) as exc:
        return False, str(exc)
    return True, message


def reset_password(email: str, new_password: str) -> tuple[bool, str]:
    try:
        message = get_runtime_services().auth_service.reset_password(email, new_password)
    except (NotFoundError, ValidationError) as exc:
        return False, str(exc)
    return True, message


def get_user(user_id: str) -> dict[str, Any] | None:
    return get_runtime_services().auth_service.get_user(user_id)


def get_public_user(user_id: str) -> dict[str, Any] | None:
    return get_runtime_services().auth_service.get_public_user(user_id)


def read_user_settings(user_id: str) -> dict[str, Any]:
    return get_runtime_services().auth_service.read_user_settings(user_id)


def update_user_settings(user_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    return get_runtime_services().auth_service.update_user_settings(user_id, updates)


def update_display_name(user_id: str, display_name: str | None) -> dict[str, Any]:
    return get_runtime_services().auth_service.update_display_name(user_id, display_name)
