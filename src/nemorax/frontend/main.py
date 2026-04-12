"""
frontend/main.py
----------------
Flet entry point - responsive across Desktop, Web, Android, iOS.
"""
from __future__ import annotations

import flet as ft

from nemorax.frontend.chat_page import ChatPage
from nemorax.frontend.config import APP_NAME, BRAND_NAME, current_theme, should_show_splash
from nemorax.frontend.responsive import is_desktop
from nemorax.frontend.splash_page import SplashPage


def _mount_fullscreen(page: ft.Page, control: ft.Control) -> None:
    page.clean()
    control.expand = True
    page.add(control)
    page.update()


async def _configure_desktop_window(page: ft.Page) -> None:
    if not is_desktop(page):
        return

    page.window.width = 1320
    page.window.height = 860
    page.window.min_width = 1040
    page.window.min_height = 700

    try:
        await page.window.center()
    except AttributeError:
        pass


async def main(page: ft.Page) -> None:
    page.title = f"{BRAND_NAME} - {APP_NAME}"
    page.padding = 0
    page.spacing = 0
    page.bgcolor = current_theme().grad_bottom
    page.theme_mode = ft.ThemeMode.DARK
    page.scroll = ft.ScrollMode.HIDDEN

    await _configure_desktop_window(page)

    def open_chat() -> None:
        _mount_fullscreen(page, ChatPage(page))

    initial_view: ft.Control
    if should_show_splash():
        initial_view = SplashPage(page, on_continue=open_chat)
    else:
        initial_view = ChatPage(page)

    _mount_fullscreen(page, initial_view)


if __name__ == "__main__":
    ft.run(main, assets_dir="assets")
