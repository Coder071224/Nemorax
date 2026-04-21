from __future__ import annotations

import asyncio
import json
import sys
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

import flet as ft

from nemorax.frontend import api_client
from nemorax.frontend.config import normalize_user_settings
from nemorax.frontend.responsive import is_web


UserInfo = dict[str, Any]

_INSTALLATION_ID_KEY = "nemorax.native.installation_id"
_SESSION_KEY = "nemorax.native.auth_session"
_SESSION_VERSION = 1


def native_auth_installation_id_key() -> str:
    return _INSTALLATION_ID_KEY


def native_auth_session_key() -> str:
    return _SESSION_KEY


def is_supported_native_auth_target(page: ft.Page) -> bool:
    if is_web(page):
        return False

    platform = getattr(page, "platform", None)
    if platform == ft.PagePlatform.ANDROID:
        return True

    return bool(platform == ft.PagePlatform.WINDOWS and getattr(sys, "frozen", False))


def sanitize_native_session_user(user: UserInfo | None) -> UserInfo | None:
    if not isinstance(user, dict):
        return None

    user_id = str(user.get("user_id", "")).strip()
    email = str(user.get("email", "")).strip()
    if not user_id or not email:
        return None

    sanitized: UserInfo = {
        "user_id": user_id,
        "email": email,
    }

    display_name = user.get("display_name")
    if isinstance(display_name, str) and display_name.strip():
        sanitized["display_name"] = display_name.strip()

    settings = normalize_user_settings(user)
    if settings:
        sanitized["settings"] = settings

    return sanitized


async def ensure_installation_id(page: ft.Page) -> str | None:
    if not is_supported_native_auth_target(page):
        return None

    preferences = _shared_preferences(page)
    existing = await preferences.get(_INSTALLATION_ID_KEY)
    if isinstance(existing, str) and existing.strip():
        return existing.strip()

    installation_id = str(uuid.uuid4())
    await preferences.set(_INSTALLATION_ID_KEY, installation_id)
    return installation_id


async def save_native_auth_session(page: ft.Page, user: UserInfo | None) -> bool:
    if not is_supported_native_auth_target(page):
        return False

    sanitized_user = sanitize_native_session_user(user)
    if sanitized_user is None:
        await clear_native_auth_session(page, clear_installation_id=False)
        return False

    installation_id = await ensure_installation_id(page)
    if not installation_id:
        return False

    payload = json.dumps(
        {
            "version": _SESSION_VERSION,
            "installation_id": installation_id,
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "user": sanitized_user,
        },
        separators=(",", ":"),
    )
    return bool(await _shared_preferences(page).set(_SESSION_KEY, payload))


async def clear_native_auth_session(
    page: ft.Page,
    *,
    clear_installation_id: bool = False,
) -> None:
    if not is_supported_native_auth_target(page):
        return

    preferences = _shared_preferences(page)
    await preferences.remove(_SESSION_KEY)
    if clear_installation_id:
        await preferences.remove(_INSTALLATION_ID_KEY)


async def restore_native_auth_session(
    page: ft.Page,
    *,
    profile_loader: Callable[[str], Awaitable[UserInfo | None]] | None = None,
) -> UserInfo | None:
    if not is_supported_native_auth_target(page):
        return None

    await ensure_installation_id(page)
    preferences = _shared_preferences(page)
    payload = await preferences.get(_SESSION_KEY)
    session_data = _parse_session_payload(payload)
    if session_data is None:
        if payload is not None:
            await clear_native_auth_session(page, clear_installation_id=False)
        return None

    saved_user = sanitize_native_session_user(session_data.get("user"))
    if saved_user is None:
        await clear_native_auth_session(page, clear_installation_id=False)
        return None

    loader = profile_loader or _default_profile_loader
    try:
        profile = await loader(saved_user["user_id"])
    except Exception:
        profile = None

    restored_user = sanitize_native_session_user(profile or saved_user)
    if profile is None or restored_user is None:
        await clear_native_auth_session(page, clear_installation_id=False)
        return None

    await save_native_auth_session(page, restored_user)
    return restored_user


def _shared_preferences(page: ft.Page) -> ft.SharedPreferences:
    for service in page.services:
        if isinstance(service, ft.SharedPreferences):
            return service

    preferences = ft.SharedPreferences()
    page.services.append(preferences)
    page.update()
    return preferences


def _parse_session_payload(payload: object) -> dict[str, Any] | None:
    if not isinstance(payload, str) or not payload.strip():
        return None

    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return None

    if not isinstance(data, dict):
        return None
    if data.get("version") != _SESSION_VERSION:
        return None
    return data


async def _default_profile_loader(user_id: str) -> UserInfo | None:
    return await asyncio.to_thread(api_client.load_user_profile, user_id)
