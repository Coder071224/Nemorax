from __future__ import annotations

import sys
import unittest
import asyncio
import contextvars
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from nemorax.frontend import preferences
from nemorax.frontend.config import (
    DEFAULT_THEME,
    apply_theme,
    current_theme,
    normalize_user_settings,
    resolve_theme_name,
    should_show_splash,
)
from nemorax.frontend.api_client import ApiClientError
from nemorax.frontend.history_service import HistoryService


class _FakePage:
    def __init__(self) -> None:
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


class FrontendPreferenceTests(unittest.TestCase):
    def test_guest_uses_defaults(self) -> None:
        self.assertEqual(resolve_theme_name(None), DEFAULT_THEME)
        self.assertTrue(should_show_splash(None))

    def test_authenticated_user_settings_are_normalized(self) -> None:
        user = {
            "user_id": "user-1",
            "settings": {
                "theme": "emerald_noir",
                "show_splash": False,
                "ignored": "value",
            },
        }

        self.assertEqual(
            normalize_user_settings(user),
            {"theme": "emerald_noir", "show_splash": False},
        )
        self.assertEqual(resolve_theme_name(user), "emerald_noir")
        self.assertFalse(should_show_splash(user))

    def test_invalid_or_missing_authenticated_settings_fall_back_to_defaults(self) -> None:
        user = {"settings": {"theme": "unknown-theme", "show_splash": "nope"}}
        self.assertEqual(resolve_theme_name(user), DEFAULT_THEME)
        self.assertTrue(should_show_splash(user))

    def test_runtime_theme_is_context_local(self) -> None:
        apply_theme("emerald_noir")

        other_context = contextvars.copy_context()
        other_context.run(apply_theme, "glacier_pearl")

        self.assertEqual(current_theme().name, "Emerald Noir")
        self.assertEqual(other_context.run(current_theme).name, "Glacier Pearl")

    def test_local_theme_keys_are_isolated_by_guest_and_user(self) -> None:
        page = _FakePage()
        store = _FakePreferences()

        def _fake_preferences(_page):
            self.assertIs(_page, page)
            return store

        original = preferences._shared_preferences
        preferences._shared_preferences = _fake_preferences
        try:
            asyncio.run(preferences.save_local_theme(page, "emerald_noir"))
            asyncio.run(preferences.save_local_theme(page, "glacier_pearl", "user-1"))
            asyncio.run(preferences.save_local_theme(page, "royal_obsidian", "user-2"))

            self.assertEqual(asyncio.run(preferences.load_local_theme(page)), "emerald_noir")
            self.assertEqual(asyncio.run(preferences.load_local_theme(page, "user-1")), "glacier_pearl")
            self.assertEqual(asyncio.run(preferences.load_local_theme(page, "user-2")), "royal_obsidian")
        finally:
            preferences._shared_preferences = original

    def test_logged_in_history_load_error_is_not_treated_as_guest_history(self) -> None:
        from nemorax.frontend import history_service

        saved = history_service.api_client.list_history
        history_service.api_client.list_history = lambda _: (_ for _ in ()).throw(
            ApiClientError("History unavailable", kind="backend_unavailable")
        )
        try:
            service = HistoryService("user-1")
            self.assertEqual(service.conversations, [])
            self.assertEqual(service.load_error, "History unavailable")
            self.assertEqual(service.user_id, "user-1")
        finally:
            history_service.api_client.list_history = saved


if __name__ == "__main__":
    unittest.main()
