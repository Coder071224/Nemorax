from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import flet as ft

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from nemorax.frontend import native_auth


class _FakePage:
    def __init__(self, *, platform, web: bool = False) -> None:
        self.platform = platform
        self.web = web
        self.services: list[object] = []

    def update(self) -> None:
        pass


class _FakePreferences:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}

    async def get(self, key: str) -> object:
        return self.values.get(key)

    async def set(self, key: str, value: object) -> bool:
        self.values[key] = value
        return True

    async def remove(self, key: str) -> bool:
        self.values.pop(key, None)
        return True


def test_native_auth_platform_gate_is_explicit(monkeypatch) -> None:
    web_page = _FakePage(platform=ft.PagePlatform.ANDROID, web=True)
    android_page = _FakePage(platform=ft.PagePlatform.ANDROID, web=False)
    windows_page = _FakePage(platform=ft.PagePlatform.WINDOWS, web=False)

    monkeypatch.setattr(sys, "frozen", False, raising=False)
    assert native_auth.is_supported_native_auth_target(web_page) is False
    assert native_auth.is_supported_native_auth_target(android_page) is True
    assert native_auth.is_supported_native_auth_target(windows_page) is False

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert native_auth.is_supported_native_auth_target(windows_page) is True


def test_save_native_auth_session_stores_installation_id_and_user(monkeypatch) -> None:
    page = _FakePage(platform=ft.PagePlatform.ANDROID)
    preferences = _FakePreferences()
    monkeypatch.setattr(native_auth, "_shared_preferences", lambda _: preferences)

    saved = asyncio.run(
        native_auth.save_native_auth_session(
            page,
            {
                "user_id": "user-123",
                "email": "user@example.com",
                "display_name": "Ace",
                "settings": {"theme": "emerald_noir"},
                "password": "not-stored",
            },
        )
    )

    assert saved is True
    assert isinstance(preferences.values[native_auth.native_auth_installation_id_key()], str)

    payload = json.loads(preferences.values[native_auth.native_auth_session_key()])
    assert payload["version"] == 1
    assert payload["user"] == {
        "user_id": "user-123",
        "email": "user@example.com",
        "display_name": "Ace",
        "settings": {"theme": "emerald_noir"},
    }


def test_restore_native_auth_session_clears_invalid_saved_state(monkeypatch) -> None:
    page = _FakePage(platform=ft.PagePlatform.ANDROID)
    preferences = _FakePreferences()
    preferences.values[native_auth.native_auth_installation_id_key()] = "install-1"
    preferences.values[native_auth.native_auth_session_key()] = "{bad json"
    monkeypatch.setattr(native_auth, "_shared_preferences", lambda _: preferences)

    restored = asyncio.run(native_auth.restore_native_auth_session(page))

    assert restored is None
    assert native_auth.native_auth_session_key() not in preferences.values
    assert preferences.values[native_auth.native_auth_installation_id_key()] == "install-1"


def test_restore_native_auth_session_validates_with_backend_profile(monkeypatch) -> None:
    page = _FakePage(platform=ft.PagePlatform.ANDROID)
    preferences = _FakePreferences()
    preferences.values[native_auth.native_auth_installation_id_key()] = "install-1"
    preferences.values[native_auth.native_auth_session_key()] = json.dumps(
        {
            "version": 1,
            "installation_id": "install-1",
            "saved_at": "2026-04-21T00:00:00+00:00",
            "user": {
                "user_id": "user-123",
                "email": "user@example.com",
            },
        }
    )
    monkeypatch.setattr(native_auth, "_shared_preferences", lambda _: preferences)

    async def _load_profile(user_id: str) -> dict[str, object] | None:
        assert user_id == "user-123"
        return {
            "user_id": "user-123",
            "email": "user@example.com",
            "display_name": "Restored User",
            "settings": {"theme": "glacier_pearl"},
        }

    restored = asyncio.run(
        native_auth.restore_native_auth_session(page, profile_loader=_load_profile)
    )

    assert restored == {
        "user_id": "user-123",
        "email": "user@example.com",
        "display_name": "Restored User",
        "settings": {"theme": "glacier_pearl"},
    }

    payload = json.loads(preferences.values[native_auth.native_auth_session_key()])
    assert payload["user"]["display_name"] == "Restored User"


def test_restore_native_auth_session_clears_when_profile_validation_fails(monkeypatch) -> None:
    page = _FakePage(platform=ft.PagePlatform.ANDROID)
    preferences = _FakePreferences()
    preferences.values[native_auth.native_auth_installation_id_key()] = "install-1"
    preferences.values[native_auth.native_auth_session_key()] = json.dumps(
        {
            "version": 1,
            "installation_id": "install-1",
            "saved_at": "2026-04-21T00:00:00+00:00",
            "user": {
                "user_id": "user-123",
                "email": "user@example.com",
            },
        }
    )
    monkeypatch.setattr(native_auth, "_shared_preferences", lambda _: preferences)

    async def _missing_profile(_: str) -> dict[str, object] | None:
        return None

    restored = asyncio.run(
        native_auth.restore_native_auth_session(page, profile_loader=_missing_profile)
    )

    assert restored is None
    assert native_auth.native_auth_session_key() not in preferences.values
