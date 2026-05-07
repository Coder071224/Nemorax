"""
frontend/main.py
----------------
Flet entry point - responsive across Desktop, Web, Android, iOS.
"""
from __future__ import annotations

import threading

import flet as ft

from nemorax.frontend import api_client
from nemorax.frontend.app_state import AppState
from nemorax.frontend.auth_session import restore_startup_auth_session
from nemorax.frontend.chat_page import ChatPage
from nemorax.frontend.config import APP_NAME, BRAND_NAME, LOGO_ASSET, current_theme, resolve_theme_name, should_show_splash
from nemorax.frontend.native_auth import load_native_auth_session_snapshot
from nemorax.frontend.preferences import load_local_theme
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


def _build_startup_loader(page: ft.Page, app_state: AppState) -> ft.Control:
    theme = app_state.activate_theme()
    page_width = float(page.width or getattr(page, "window_width", None) or 390)
    page_height = float(page.height or getattr(page, "window_height", None) or 760)
    compact = page_width < 520 or page_height < 720
    card_width = min(max(page_width - 32, 280), 420)
    logo_size = 52 if compact else 62

    return ft.Container(
        key="startup-loader-root",
        expand=True,
        bgcolor=theme.grad_bottom,
        alignment=ft.Alignment(0, 0),
        gradient=ft.LinearGradient(
            begin=ft.Alignment(-1, -1),
            end=ft.Alignment(1, 1),
            colors=[theme.grad_top, theme.grad_mid, theme.grad_bottom],
        ),
        content=ft.Container(
            width=card_width,
            margin=ft.Margin.symmetric(horizontal=16),
            padding=ft.Padding.symmetric(
                horizontal=22 if compact else 28,
                vertical=24 if compact else 30,
            ),
            border_radius=28,
            bgcolor=ft.Colors.with_opacity(0.22, theme.sidebar_bg),
            border=ft.Border.all(1, ft.Colors.with_opacity(0.18, theme.border)),
            shadow=ft.BoxShadow(
                spread_radius=0,
                blur_radius=24,
                color=ft.Colors.with_opacity(0.24, theme.shadow),
                offset=ft.Offset(0, 14),
            ),
            content=ft.Column(
                key="startup-loader-card",
                tight=True,
                spacing=14 if compact else 16,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Container(
                        width=logo_size,
                        height=logo_size,
                        border_radius=18,
                        bgcolor=ft.Colors.with_opacity(0.14, theme.text_primary),
                        border=ft.Border.all(1, ft.Colors.with_opacity(0.22, theme.text_primary)),
                        alignment=ft.Alignment(0, 0),
                        content=ft.Image(
                            src=LOGO_ASSET,
                            width=logo_size - 14,
                            height=logo_size - 14,
                            fit=ft.BoxFit.CONTAIN,
                        ),
                    ),
                    ft.Column(
                        tight=True,
                        spacing=4,
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            ft.Text(
                                APP_NAME,
                                size=24 if compact else 28,
                                weight=ft.FontWeight.W_900,
                                color=theme.text_primary,
                            ),
                            ft.Text(
                                f"by {BRAND_NAME}",
                                size=12,
                                weight=ft.FontWeight.W_700,
                                color=theme.accent,
                            ),
                        ],
                    ),
                    ft.Container(height=2 if compact else 4),
                    ft.ProgressRing(
                        key="startup-loader-progress",
                        width=30 if compact else 34,
                        height=30 if compact else 34,
                        stroke_width=3,
                        color=theme.accent,
                    ),
                    ft.Column(
                        tight=True,
                        spacing=6,
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            ft.Text(
                                key="startup-loader-title",
                                value="Restoring your session...",
                                size=15 if compact else 16,
                                weight=ft.FontWeight.W_800,
                                color=theme.text_primary,
                                text_align=ft.TextAlign.CENTER,
                            ),
                            ft.Text(
                                key="startup-loader-subtitle",
                                value="Preparing your workspace.",
                                size=12 if compact else 13,
                                color=theme.text_secondary,
                                text_align=ft.TextAlign.CENTER,
                            ),
                        ],
                    ),
                    ft.Text(
                        BRAND_NAME,
                        size=11,
                        weight=ft.FontWeight.W_700,
                        color=theme.text_muted,
                    ),
                ],
            ),
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
    initial_theme_name = await load_local_theme(page)
    saved_user = await load_native_auth_session_snapshot(page)
    if saved_user:
        initial_theme_name = resolve_theme_name(saved_user)
        settings = saved_user.get("settings", {})
        if not isinstance(settings, dict) or "theme" not in settings:
            initial_theme_name = await load_local_theme(page, saved_user["user_id"])

    app_state = AppState(initial_theme_name)
    app_state.activate_theme()
    page.title = f"{APP_NAME} by {BRAND_NAME}"
    page.padding = 0
    page.spacing = 0
    page.bgcolor = current_theme().grad_bottom
    page.theme_mode = ft.ThemeMode.DARK
    page.scroll = ft.ScrollMode.HIDDEN
    page.horizontal_alignment = ft.CrossAxisAlignment.STRETCH
    page.vertical_alignment = ft.MainAxisAlignment.START

    await _configure_desktop_window(page)
    _mount_fullscreen(page, _build_startup_loader(page, app_state))
    restored_user = await restore_startup_auth_session(page)
    if restored_user:
        initial_theme_name = resolve_theme_name(restored_user)
        settings = restored_user.get("settings", {})
        if not isinstance(settings, dict) or "theme" not in settings:
            initial_theme_name = await load_local_theme(page, restored_user["user_id"])
    app_state.set_theme(initial_theme_name)
    page.bgcolor = current_theme().grad_bottom

    def open_chat() -> None:
        _mount_fullscreen(
            page,
            ChatPage(
                page,
                initial_user=restored_user,
                initial_theme_name=initial_theme_name,
                app_state=app_state,
            ),
        )

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
        initial_view = ChatPage(
            page,
            initial_user=restored_user,
            initial_theme_name=initial_theme_name,
            app_state=app_state,
        )

    _mount_fullscreen(page, initial_view)


if __name__ == "__main__":
    ft.run(main, assets_dir="assets")
