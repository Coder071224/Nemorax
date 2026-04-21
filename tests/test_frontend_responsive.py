from __future__ import annotations

import sys
import unittest
from pathlib import Path

import flet as ft

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from nemorax.frontend.responsive import get_layout_config, should_use_mobile_layout


class _FakePage:
    def __init__(self, *, width: float, height: float, platform, web: bool) -> None:
        self.width = width
        self.height = height
        self.platform = platform
        self.web = web


class FrontendResponsiveTests(unittest.TestCase):
    def test_mobile_web_portrait_uses_mobile_layout(self) -> None:
        page = _FakePage(width=390, height=844, platform=ft.PagePlatform.WINDOWS, web=True)

        self.assertTrue(should_use_mobile_layout(page))
        self.assertTrue(get_layout_config(page)["is_mobile"])

    def test_mobile_web_landscape_phone_still_uses_mobile_layout(self) -> None:
        page = _FakePage(width=844, height=390, platform=ft.PagePlatform.WINDOWS, web=True)

        self.assertTrue(should_use_mobile_layout(page))
        self.assertTrue(get_layout_config(page)["is_mobile"])

    def test_desktop_web_keeps_desktop_layout(self) -> None:
        page = _FakePage(width=1280, height=800, platform=ft.PagePlatform.WINDOWS, web=True)

        self.assertFalse(should_use_mobile_layout(page))
        self.assertFalse(get_layout_config(page)["is_mobile"])


if __name__ == "__main__":
    unittest.main()
