"""
frontend/main.py
----------------
Flet entry point - responsive across Desktop, Web, Android, iOS.
"""
from __future__ import annotations

import threading

import flet as ft

from nemorax.frontend import api_client
from nemorax.frontend.auth_session import restore_startup_auth_session
from nemorax.frontend.chat_page import ChatPage
from nemorax.frontend.config import APP_NAME, BRAND_NAME, current_theme, should_show_splash
from nemorax.frontend.responsive import is_desktop, is_web
from nemorax.frontend.splash_page import SplashPage


def _clear_page_overlays(page: ft.Page) -> None:
    if not page.overlay:
        return
    page.overlay.clear()


def _mount_fullscreen(page: ft.Page, control: ft.Control) -> None:
    _clear_page_overlays(page)
    page.clean()
    control.expand = True
    page.add(control)
    page.update()


def _build_startup_loader() -> ft.Control:
    theme = current_theme()
    return ft.Container(
        expand=True,
        alignment=ft.Alignment(0, 0),
        content=ft.Column(
            tight=True,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                ft.ProgressRing(width=28, height=28, stroke_width=3, color=theme.accent),
                ft.Text(
                    "Restoring session...",
                    size=13,
                    color=theme.text_secondary,
                ),
            ],
        ),
    )


async def _configure_desktop_window(page: ft.Page) -> None:
    if is_web(page) or not is_desktop(page):
        return

    page.window.width = 1320
    page.window.height = 860
    page.window.min_width = 1040
    page.window.min_height = 700

    try:
        await page.window.center()
    except Exception:
        pass


async def main(page: ft.Page) -> None:
    page.title = f"{BRAND_NAME} - {APP_NAME}"
    page.padding = 0
    page.spacing = 0
    page.bgcolor = current_theme().grad_bottom
    page.theme_mode = ft.ThemeMode.DARK
    page.scroll = ft.ScrollMode.HIDDEN
    page.horizontal_alignment = ft.CrossAxisAlignment.STRETCH
    page.vertical_alignment = ft.MainAxisAlignment.START

    await _configure_desktop_window(page)
    _mount_fullscreen(page, _build_startup_loader())
    restored_user = await restore_startup_auth_session(page)

    def open_chat() -> None:
        _mount_fullscreen(page, ChatPage(page, initial_user=restored_user))

    def persist_restored_user_splash(show_splash: bool) -> None:
        if not restored_user:
            return
        settings = restored_user.get("settings", {})
        if not isinstance(settings, dict):
            settings = {}
        settings["show_splash"] = show_splash
        restored_user["settings"] = settings
        threading.Thread(
            target=lambda: api_client.save_user_settings(
                restored_user["user_id"],
                {"show_splash": show_splash},
            ),
            daemon=True,
        ).start()

    initial_view: ft.Control
    if should_show_splash(restored_user):
        initial_view = SplashPage(
            page,
            on_continue=open_chat,
            on_splash_preference_change=persist_restored_user_splash if restored_user else None,
        )
    else:
        initial_view = ChatPage(page, initial_user=restored_user)

    _mount_fullscreen(page, initial_view)


if __name__ == "__main__":
    ft.run(main, assets_dir="assets")
