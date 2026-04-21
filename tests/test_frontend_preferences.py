from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from nemorax.frontend.config import DEFAULT_THEME, normalize_user_settings, resolve_theme_name, should_show_splash


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


if __name__ == "__main__":
    unittest.main()
