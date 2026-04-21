from __future__ import annotations

import asyncio
from typing import Any

import flet as ft

from nemorax.frontend import api_client
from nemorax.frontend.native_auth import (
    clear_native_auth_session,
    restore_native_auth_session,
    sanitize_native_session_user,
    save_native_auth_session,
)


UserInfo = dict[str, Any]


async def restore_startup_auth_session(page: ft.Page) -> UserInfo | None:
    return await restore_native_auth_session(page)


async def finalize_login_auth_session(page: ft.Page, user: UserInfo | None) -> UserInfo | None:
    return await _resolve_auth_session(page, user, allow_fallback_user=True)


async def refresh_auth_session(page: ft.Page, user: UserInfo | None) -> UserInfo | None:
    return await _resolve_auth_session(page, user, allow_fallback_user=False)


async def clear_auth_session(page: ft.Page) -> None:
    await clear_native_auth_session(page, clear_installation_id=False)


async def _resolve_auth_session(
    page: ft.Page,
    user: UserInfo | None,
    *,
    allow_fallback_user: bool,
) -> UserInfo | None:
    candidate = sanitize_native_session_user(user)
    if candidate is None:
        await clear_auth_session(page)
        return None

    profile = await asyncio.to_thread(api_client.load_user_profile, candidate["user_id"])
    resolved = sanitize_native_session_user(profile)
    if resolved is None and allow_fallback_user:
        resolved = candidate

    if resolved is None:
        await clear_auth_session(page)
        return None

    await save_native_auth_session(page, resolved)
    return resolved
