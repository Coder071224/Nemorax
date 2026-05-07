from __future__ import annotations

import flet as ft

from nemorax.frontend.config import DEFAULT_THEME, THEMES


_THEME_GUEST_KEY = "nemorax.theme.guest"
_THEME_USER_PREFIX = "nemorax.theme.user."


def theme_guest_key() -> str:
    return _THEME_GUEST_KEY


def theme_user_key(user_id: str) -> str:
    return f"{_THEME_USER_PREFIX}{user_id.strip()}"


def normalize_theme_name(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    theme_name = value.strip()
    return theme_name if theme_name in THEMES else None


async def load_local_theme(page: ft.Page, user_id: str | None = None) -> str:
    key = theme_user_key(user_id) if user_id else theme_guest_key()
    try:
        value = await _shared_preferences(page).get(key)
    except Exception:
        return DEFAULT_THEME
    return normalize_theme_name(value) or DEFAULT_THEME


async def save_local_theme(page: ft.Page, theme_name: str, user_id: str | None = None) -> bool:
    normalized = normalize_theme_name(theme_name)
    if normalized is None:
        return False

    key = theme_user_key(user_id) if user_id else theme_guest_key()
    try:
        return bool(await _shared_preferences(page).set(key, normalized))
    except Exception:
        return False


def _shared_preferences(page: ft.Page) -> ft.SharedPreferences:
    for service in page.services:
        if isinstance(service, ft.SharedPreferences):
            return service

    preferences = ft.SharedPreferences()
    page.services.append(preferences)
    try:
        page.update()
    except Exception:
        pass
    return preferences
