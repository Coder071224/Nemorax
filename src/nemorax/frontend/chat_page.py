"""
frontend/chat_page.py
---------------------
Main Nemorax chat interface for Nemis - responsive across Desktop, Web, Android, iOS.
"""
from __future__ import annotations

import asyncio
import random
import threading
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

import flet as ft

from nemorax.frontend import api_client
from nemorax.frontend.account_dialog import AccountDialog
from nemorax.frontend.config import (
    APP_NAME,
    DEFAULT_THEME,
    GENERIC_GREETING_NAMES,
    LOGO_ASSET,
    SUGGESTED_QUESTIONS,
    THEMES,
    apply_theme,
    current_theme,
    set_show_splash,
    should_show_splash,
)
from nemorax.frontend.history_service import Conversation, HistoryService, Message
from nemorax.frontend.message_bubble import assistant_bubble, typing_indicator, user_bubble
from nemorax.frontend.responsive import get_layout_config
from nemorax.frontend.sidebar import SidebarPanel
from nemorax.frontend.splash_page import SplashPage
from nemorax.frontend.time_utils import ph_now


UserInfo = dict[str, Any]

_SIDEBAR_EXPANDED_WIDTH = 272
_SIDEBAR_COLLAPSED_WIDTH = 76
_SETTINGS_PANEL_WIDTH = 360
_MOBILE_BREAKPOINT = 800
_THEME_SAVE_DELAY_SECONDS = 0.08
_AUTH_BANNER_SECONDS = 4.0
_MOBILE_WEB_RESIZE_WIDTH_DELTA = 12.0


class ChatPage(ft.Container):
    def __init__(self, page: ft.Page) -> None:
        super().__init__()
        self._page = page
        self._history = HistoryService()
        self._history.new_conversation()

        apply_theme(DEFAULT_THEME)
        self._sending = False
        self._sidebar_expanded = False
        self._settings_open = False
        self._theme_name = DEFAULT_THEME
        self._session_greeting_name = self._roll_greeting_name()

        self._mobile_backdrop: ft.Container | None = None
        self._mobile_drawer_container: ft.Container | None = None

        self._current_user: UserInfo | None = None
        self._auth_banner: tuple[str, str] | None = None
        self._banner_clear_task = None
        self._typing_session_id: str | None = None
        self._pending_request_session_id: str | None = None
        self._inline_error: tuple[str, str] | None = None

        self._backend_available = False
        self._provider_available = False
        self._provider_label = "Model"
        self._provider_model = ""

        self._is_mobile = False
        self._custom_drawer_open = False

        self._hero_view: ft.Control | None = None
        self._message_list: ft.ListView | None = None
        self._chat_host: ft.Container | None = None
        self._sidebar_host: ft.Container | None = None
        self._settings_panel: ft.Container | None = None
        self._input: ft.TextField | None = None
        self._send_button: ft.IconButton | None = None
        self._chat_bottom_anchor = ft.Container(key="chat-bottom-anchor", height=1)
        self._history_context_menu_overlay: ft.Stack | None = None
        self._history_delete_sheet: ft.BottomSheet | None = None
        self._scroll_to_latest_requested = False
        self._last_viewport_width = self._page_width()
        self._last_viewport_height = self._page_height()

        self.expand = True
        self.padding = 0
        self.margin = 0

        self._update_mobile_state()
        self._refresh()

        self._page.on_resize = self._on_resize
        self._page.run_task(self._post_mount_refresh)
        self._page.run_task(self._check_health)

    # Safe update helpers

    def _control_is_attached(self, control: ft.Control | None) -> bool:
        if control is None:
            return False
        try:
            return control.page is not None
        except Exception:
            return False

    def _safe_update(self, control: ft.Control | None) -> None:
        if not self._control_is_attached(control):
            return
        try:
            control.update()
        except Exception:
            pass

    def _safe_page_update(self) -> None:
        try:
            self._page.update()
        except Exception:
            pass

    def _append_overlay_control(self, control: ft.Control) -> None:
        if control not in self._page.overlay:
            self._page.overlay.append(control)
        self._safe_page_update()

    def _remove_overlay_control(self, control: ft.Control | None) -> None:
        if control is None:
            return
        if control in self._page.overlay:
            self._page.overlay.remove(control)
        self._safe_page_update()

    def _run_in_thread(self, worker: Callable[[], None]) -> None:
        threading.Thread(target=worker, daemon=True).start()

    # Health check

    async def _check_health(self) -> None:
        try:
            health = await asyncio.to_thread(api_client.check_health)
            provider = health.get("provider", {})
            provider_label = ""
            provider_model = ""
            provider_available = False
            if isinstance(provider, dict):
                label = provider.get("label")
                model = provider.get("model")
                provider_label = label.strip() if isinstance(label, str) and label.strip() else ""
                provider_model = model.strip() if isinstance(model, str) and model.strip() else ""
                provider_available = bool(provider.get("available", False))

            self._backend_available = health.get("status") == "ok"
            self._provider_available = provider_available or bool(health.get("provider_available", False))
            self._provider_label = provider_label or "Model"
            self._provider_model = provider_model
        except Exception:
            self._backend_available = False
            self._provider_available = False
            self._provider_label = "Model"
            self._provider_model = ""

        self._refresh()
        self._safe_update(self)

    # General state helpers

    def _page_width(self) -> float:
        return float(self._page.width or getattr(self._page, "window_width", None) or 1320)

    def _page_height(self) -> float:
        return float(self._page.height or getattr(self._page, "window_height", None) or 860)

    def _is_mobile_web_view(self, width: float | None = None) -> bool:
        resolved_width = self._page_width() if width is None else float(width)
        return bool(getattr(self._page, "web", False)) and resolved_width < _MOBILE_BREAKPOINT

    def _current_conversation_has_messages(self) -> bool:
        conversation = self._history.current_conversation
        return bool(conversation and conversation.messages)

    def _clear_input(self) -> None:
        if self._input is None:
            return
        self._input.value = ""
        self._safe_update(self._input)

    def _set_send_enabled(self, enabled: bool) -> None:
        if self._send_button is None:
            return
        self._send_button.disabled = not enabled
        self._safe_update(self._send_button)

    def _show_auth_banner(self, message: str, kind: str = "success") -> None:
        self._auth_banner = (kind, message)

        if self._banner_clear_task is not None:
            try:
                if not self._banner_clear_task.done():
                    self._banner_clear_task.cancel()
            except Exception:
                pass

        async def _auto_clear() -> None:
            await asyncio.sleep(_AUTH_BANNER_SECONDS)
            self._auth_banner = None
            self._refresh()
            self._safe_update(self)

        self._banner_clear_task = self._page.run_task(_auto_clear)

    def _cancel_pending_chat_request(self) -> None:
        self._pending_request_session_id = None
        self._typing_session_id = None
        self._inline_error = None
        self._sending = False
        self._set_send_enabled(True)

    def _roll_greeting_name(self) -> str:
        return random.choice(GENERIC_GREETING_NAMES)

    def _reset_session_greeting_name(self) -> None:
        self._session_greeting_name = self._roll_greeting_name()

    def _current_greeting_name(self) -> str:
        if self._current_user:
            display_name = self._current_user.get("display_name")
            if isinstance(display_name, str) and display_name.strip():
                return display_name.strip()
        return self._session_greeting_name

    def _resolved_theme_name(self, user: UserInfo | None = None) -> str:
        source = user if user is not None else self._current_user
        if not source:
            return DEFAULT_THEME

        settings = source.get("settings", {})
        if not isinstance(settings, dict):
            return DEFAULT_THEME

        theme = settings.get("theme")
        if isinstance(theme, str) and theme in THEMES:
            return theme
        return DEFAULT_THEME

    def _set_theme_runtime(self, name: str) -> None:
        theme_name = name if name in THEMES else DEFAULT_THEME
        apply_theme(theme_name)
        self._theme_name = theme_name

    def _find_conversation(self, conversation_id: str) -> Conversation | None:
        current = self._history.current_conversation
        if current is not None and current.id == conversation_id:
            return current

        for conversation in self._history.conversations:
            if conversation.id == conversation_id:
                return conversation

        return None

    def _append_message_to_conversation(
        self,
        conversation_id: str,
        role: str,
        content: str,
    ) -> Message | None:
        conversation = self._find_conversation(conversation_id)
        if conversation is None:
            return None

        message = Message(role=role, content=content)
        conversation.messages.append(message)
        conversation.updated_at = message.timestamp
        conversation.is_placeholder = False
        return message

    def _clear_inline_error(self, conversation_id: str | None = None) -> None:
        if conversation_id is None:
            self._inline_error = None
            return

        if self._inline_error and self._inline_error[0] == conversation_id:
            self._inline_error = None

    def _get_theme_key_from_palette(self) -> str:
        current_name = current_theme().name
        for key, palette in THEMES.items():
            if palette.name == current_name:
                return key
        return next(iter(THEMES.keys()))

    # Resize / layout

    def _on_resize(self, _: ft.PageResizeEvent) -> None:
        width = self._page_width()
        height = self._page_height()
        width_delta = abs(width - self._last_viewport_width)

        if self._is_mobile_web_view(width) and width_delta < _MOBILE_WEB_RESIZE_WIDTH_DELTA:
            self._last_viewport_width = width
            self._last_viewport_height = height
            return

        self._last_viewport_width = width
        self._last_viewport_height = height
        self._update_mobile_state()
        self._refresh()
        self._safe_update(self)

    async def _post_mount_refresh(self) -> None:
        await asyncio.sleep(_THEME_SAVE_DELAY_SECONDS)
        self._update_mobile_state()
        self._refresh()
        self._safe_update(self)

    def _update_mobile_state(self) -> None:
        was_mobile = self._is_mobile
        self._is_mobile = self._page_width() < _MOBILE_BREAKPOINT

        if self._is_mobile and not was_mobile:
            self._settings_open = False
            self._custom_drawer_open = False
        elif not self._is_mobile and was_mobile:
            self._custom_drawer_open = False

    # Mobile drawer

    def _sync_mobile_drawer(self) -> None:
        if not self._is_mobile:
            return

        if self._mobile_backdrop is None or self._mobile_drawer_container is None:
            had_messages = self._current_conversation_has_messages()
            self._refresh()
            if had_messages:
                self._render_conversation()
            self._safe_update(self)
            return

        drawer_width = self._mobile_drawer_container.width or 280
        self._mobile_backdrop.visible = self._custom_drawer_open
        self._mobile_drawer_container.left = 0 if self._custom_drawer_open else -drawer_width

        self._safe_update(self._mobile_backdrop)
        self._safe_update(self._mobile_drawer_container)
        self._safe_update(self)

    def _close_drawer(self, e=None) -> None:
        if not self._custom_drawer_open:
            return
        self._custom_drawer_open = False
        self._sync_mobile_drawer()

    def _open_drawer(self, e=None) -> None:
        if not self._is_mobile:
            return
        self._custom_drawer_open = True
        self._sync_mobile_drawer()

    def _drawer_subtitle(self, conversation: Conversation) -> str:
        stamp = conversation.updated_at
        today = ph_now().date()

        if stamp.date() == today:
            return stamp.strftime("Today | %I:%M %p").replace(" 0", " ")
        if stamp.date() == today - timedelta(days=1):
            return stamp.strftime("Yesterday | %I:%M %p").replace(" 0", " ")
        return stamp.strftime("%b %d | %I:%M %p").replace(" 0", " ")

    def _build_drawer_history_item(
        self,
        conversation: Conversation,
        selected: bool,
        cfg: dict[str, Any],
    ) -> ft.Control:
        theme = current_theme()
        subtitle = self._drawer_subtitle(conversation)

        return ft.Container(
            padding=ft.Padding.symmetric(horizontal=16, vertical=10),
            border_radius=12,
            bgcolor=ft.Colors.with_opacity(0.14, theme.accent) if selected else None,
            on_click=lambda _, cid=conversation.id: self._load_conversation_and_close_drawer(cid),
            content=ft.Column(
                spacing=2,
                controls=[
                    ft.Text(
                        conversation.title,
                        size=cfg["font_size_body"],
                        weight=ft.FontWeight.W_600,
                        color=theme.text_primary,
                        max_lines=1,
                        overflow=ft.TextOverflow.ELLIPSIS,
                    ),
                    ft.Text(
                        subtitle,
                        size=cfg["font_size_small"],
                        color=theme.text_muted,
                    ),
                ],
            ),
        )

    def _load_conversation_and_close_drawer(self, conversation_id: str) -> None:
        self._load_conversation(conversation_id)
        self._close_drawer()

    def _toggle_settings_mobile(self, e=None) -> None:
        self._close_drawer()
        self._open_settings_dialog()

    def _build_custom_drawer(self, cfg: dict[str, Any]) -> ft.Container:
        theme = current_theme()
        current_id = self._history.current_conversation.id if self._history.current_conversation else None

        def drawer_button(
            icon: ft.IconData,
            label: str,
            on_click: Callable[..., None],
            *,
            accent: bool = False,
        ) -> ft.Container:
            return ft.Container(
                padding=ft.Padding.symmetric(
                    horizontal=16,
                    vertical=max(12, (cfg["button_height"] - 20) // 2),
                ),
                on_click=on_click,
                content=ft.Row(
                    controls=[
                        ft.Icon(
                            icon,
                            size=20,
                            color=theme.accent if accent else theme.text_secondary,
                        ),
                        ft.Text(
                            label,
                            size=cfg["font_size_body"],
                            weight=ft.FontWeight.W_600,
                            color=theme.text_primary,
                        ),
                    ],
                    spacing=12,
                ),
            )

        if self._current_user:
            account_label = self._current_user["email"]
            account_icon = ft.Icons.PERSON_ROUNDED
        else:
            account_label = "Guest | Sign In"
            account_icon = ft.Icons.PERSON_OUTLINE_ROUNDED

        history_list = ft.ListView(
            spacing=8,
            expand=True,
            auto_scroll=False,
            padding=ft.Padding.symmetric(horizontal=12),
            controls=[
                self._build_drawer_history_item(conversation, conversation.id == current_id, cfg)
                for conversation in self._history.get_all_conversations()[:10]
            ],
        )

        content = ft.Column(
            spacing=0,
            expand=True,
            controls=[
                ft.Container(
                    padding=ft.Padding.symmetric(horizontal=16, vertical=20),
                    content=ft.Row(
                        controls=[
                            ft.Text(
                                "Menu",
                                size=18,
                                weight=ft.FontWeight.W_700,
                                color=theme.text_primary,
                            ),
                            ft.Container(expand=True),
                            ft.IconButton(
                                icon=ft.Icons.CLOSE_ROUNDED,
                                icon_color=theme.text_secondary,
                                on_click=self._close_drawer,
                            ),
                        ]
                    ),
                ),
                ft.Divider(height=1, color=ft.Colors.with_opacity(0.20, theme.border)),
                drawer_button(
                    ft.Icons.ADD_ROUNDED,
                    "New chat",
                    lambda _: (self._handle_new_chat(), self._close_drawer()),
                    accent=True,
                ),
                drawer_button(
                    ft.Icons.TUNE_ROUNDED,
                    "Settings",
                    self._toggle_settings_mobile,
                ),
                drawer_button(
                    account_icon,
                    account_label,
                    lambda _: (self._close_drawer(), self._handle_account()),
                ),
                drawer_button(
                    ft.Icons.CARD_TRAVEL_ROUNDED,
                    "Show welcome",
                    lambda _: (self._handle_show_splash(), self._close_drawer()),
                ),
                ft.Divider(height=1, color=ft.Colors.with_opacity(0.20, theme.border)),
                ft.Container(
                    padding=ft.Padding.only(left=16, right=16, top=10, bottom=8),
                    content=ft.Text(
                        "Recent chats",
                        size=cfg["font_size_small"],
                        weight=ft.FontWeight.W_700,
                        color=theme.text_muted,
                    ),
                ),
                history_list,
                drawer_button(
                    ft.Icons.INFO_OUTLINE_ROUNDED,
                    "About",
                    lambda _: (self._handle_info(), self._close_drawer()),
                ),
                drawer_button(
                    ft.Icons.RATE_REVIEW_OUTLINED,
                    "Feedback",
                    lambda _: (self._handle_feedback(), self._close_drawer()),
                ),
                ft.Container(height=10),
            ],
        )

        return ft.Container(
            width=cfg["drawer_width"],
            bgcolor=theme.sidebar_bg,
            border_radius=ft.BorderRadius.only(top_right=18, bottom_right=18),
            shadow=ft.BoxShadow(
                blur_radius=20,
                spread_radius=0,
                offset=ft.Offset(4, 0),
                color=ft.Colors.with_opacity(0.30, theme.shadow),
            ),
            content=content,
        )

    # Settings

    def _close_settings_dialog(self, ref: ft.Ref[ft.AlertDialog]) -> None:
        if ref.current is None:
            return
        ref.current.open = False
        self._safe_page_update()

    def _open_settings_dialog(self) -> None:
        theme = current_theme()
        dialog_ref = ft.Ref[ft.AlertDialog]()
        page_width = float(self._page.width or 360)
        dialog_width = min(max(page_width - 24, 260), 340)

        dialog = ft.AlertDialog(
            ref=dialog_ref,
            bgcolor=theme.dialog_bg,
            shape=ft.RoundedRectangleBorder(radius=24),
            content=ft.Container(
                width=dialog_width,
                padding=ft.Padding.all(16),
                content=ft.Column(
                    spacing=12,
                    tight=True,
                    controls=[
                        ft.Text(
                            "Settings",
                            size=20,
                            weight=ft.FontWeight.W_800,
                            color=theme.text_primary,
                        ),
                        ft.Text(
                            "Choose theme and behavior",
                            size=12,
                            color=theme.text_secondary,
                        ),
                        ft.Divider(height=1),
                        ft.Text(
                            "Appearance",
                            size=12,
                            weight=ft.FontWeight.W_700,
                            color=theme.text_muted,
                        ),
                        ft.Column(
                            spacing=10,
                            controls=[self._build_theme_card(theme_key) for theme_key in THEMES],
                        ),
                        ft.Text(
                            "Behavior",
                            size=12,
                            weight=ft.FontWeight.W_700,
                            color=theme.text_muted,
                        ),
                        self._build_welcome_toggle_card(
                            on_change=lambda event: set_show_splash(bool(event.control.value))
                        ),
                    ],
                ),
            ),
            actions=[
                ft.TextButton(
                    "Close",
                    on_click=lambda _: self._close_settings_dialog(dialog_ref),
                    style=ft.ButtonStyle(color=theme.accent),
                )
            ],
        )

        self._page.overlay.append(dialog)
        dialog.open = True
        self._safe_page_update()

    def _toggle_settings(self, e=None) -> None:
        if self._is_mobile:
            self._open_settings_dialog()
            return

        self._settings_open = not self._settings_open
        if self._settings_panel is None:
            return

        self._settings_panel.width = _SETTINGS_PANEL_WIDTH if self._settings_open else 0
        if self._settings_panel.content is not None:
            self._settings_panel.content.visible = self._settings_open
        self._safe_update(self._settings_panel)

    def _apply_theme(self, name: str) -> None:
        theme_name = name if name in THEMES else DEFAULT_THEME
        if theme_name == self._theme_name:
            if self._is_mobile:
                self._custom_drawer_open = False
            return

        self._set_theme_runtime(theme_name)

        if self._current_user:
            current_settings = self._current_user.get("settings", {})
            if not isinstance(current_settings, dict):
                current_settings = {}
            current_settings["theme"] = theme_name
            self._current_user["settings"] = current_settings
            self._run_in_thread(
                lambda: api_client.save_user_settings(
                    self._current_user["user_id"],
                    {"theme": theme_name},
                )
            )

        if self._is_mobile:
            self._custom_drawer_open = False

        had_messages = self._current_conversation_has_messages()

        self._refresh()
        self._safe_update(self)

        if had_messages:
            self._render_conversation()
        else:
            self._refresh_sidebar()

    # UI assembly

    def _refresh(self) -> None:
        theme = current_theme()
        self.width = float(self._page.width or 1320)
        self.bgcolor = theme.grad_bottom
        self.gradient = None
        if self._current_conversation_has_messages():
            self._request_scroll_to_latest()
        self.content = self._assemble()
        self._render_conversation()

    def _glass_card(self, control: ft.Control, *, padding: ft.Padding | None = None) -> ft.Container:
        theme = current_theme()
        return ft.Container(
            expand=True,
            content=control,
            padding=padding or ft.Padding.all(20),
            bgcolor=theme.surface,
            border_radius=28,
            border=ft.Border.all(1, ft.Colors.with_opacity(0.22, theme.border)),
            shadow=ft.BoxShadow(
                blur_radius=34,
                spread_radius=0,
                offset=ft.Offset(0, 18),
                color=ft.Colors.with_opacity(0.24, theme.shadow),
            ),
        )

    def _build_header(self, cfg: dict[str, Any]) -> ft.Control:
        theme = current_theme()

        if not self._backend_available:
            status_text = "Backend offline"
            status_color = theme.error
        elif not self._provider_available:
            status_text = "Model not ready"
            status_color = theme.error
        else:
            status_text = "Model ready"
            status_color = theme.success

        left_controls: list[ft.Control] = []
        if self._is_mobile:
            left_controls.append(
                ft.IconButton(
                    icon=ft.Icons.MENU_ROUNDED,
                    icon_color=theme.accent,
                    tooltip="Menu",
                    width=cfg["button_height"] - 2,
                    height=cfg["button_height"] - 2,
                    style=ft.ButtonStyle(
                        shape=ft.RoundedRectangleBorder(radius=14),
                        padding=ft.Padding.all(0),
                    ),
                    on_click=self._open_drawer,
                )
            )

        left_controls.extend(
            [
                ft.Image(
                    src=LOGO_ASSET,
                    width=cfg["logo_size_header"],
                    height=cfg["logo_size_header"],
                    fit=ft.BoxFit.CONTAIN,
                ),
                ft.Column(
                    spacing=2,
                    tight=True,
                    expand=True,
                    controls=[
                        ft.Text(
                            APP_NAME,
                            size=cfg["font_size_title"],
                            weight=ft.FontWeight.W_800,
                            color=theme.text_primary,
                            max_lines=1,
                            overflow=ft.TextOverflow.ELLIPSIS,
                        ),
                        ft.Text(
                            "Campus assistant for NEMSU",
                            size=cfg["font_size_subtitle"],
                            color=theme.text_secondary,
                            max_lines=1,
                            overflow=ft.TextOverflow.ELLIPSIS,
                        ),
                    ],
                ),
            ]
        )

        if self._current_user:
            account_icon = ft.Icons.PERSON_ROUNDED
            account_tooltip = self._current_user["email"]
            account_color = theme.success
        else:
            account_icon = ft.Icons.PERSON_OUTLINE_ROUNDED
            account_tooltip = "Sign In / Guest"
            account_color = theme.text_secondary

        header_row = ft.Row(
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                ft.Row(
                    controls=left_controls,
                    spacing=10 if self._is_mobile else 12,
                    expand=True,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Row(
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.Container(
                            visible=not self._is_mobile,
                            padding=ft.Padding.symmetric(horizontal=14, vertical=10),
                            border_radius=18,
                            bgcolor=ft.Colors.with_opacity(0.12, status_color),
                            border=ft.Border.all(
                                1,
                                ft.Colors.with_opacity(0.30, status_color),
                            ),
                            content=ft.Row(
                                tight=True,
                                spacing=8,
                                controls=[
                                    ft.Icon(ft.Icons.CIRCLE, size=10, color=status_color),
                                    ft.Text(
                                        status_text,
                                        size=12,
                                        color=theme.text_primary,
                                        weight=ft.FontWeight.W_600,
                                    ),
                                ],
                            ),
                        ),
                        ft.IconButton(
                            icon=account_icon,
                            icon_color=account_color,
                            tooltip=account_tooltip,
                            width=cfg["button_height"] - 2,
                            height=cfg["button_height"] - 2,
                            style=ft.ButtonStyle(
                                bgcolor=ft.Colors.with_opacity(0.10, account_color),
                                shape=ft.RoundedRectangleBorder(radius=14),
                            ),
                            on_click=self._handle_account,
                        ),
                    ],
                ),
            ],
        )

        banner = ft.Container(height=0)
        if self._auth_banner:
            kind, message = self._auth_banner
            banner_color = theme.success if kind == "success" else theme.error
            banner = ft.Container(
                margin=ft.Margin.only(top=12),
                padding=ft.Padding.symmetric(horizontal=14, vertical=12),
                border_radius=16,
                bgcolor=ft.Colors.with_opacity(0.16, banner_color),
                border=ft.Border.all(1, ft.Colors.with_opacity(0.35, banner_color)),
                content=ft.Row(
                    controls=[
                        ft.Text(
                            message,
                            color=theme.text_primary,
                            weight=ft.FontWeight.W_700,
                            expand=True,
                        )
                    ]
                ),
            )

        return ft.Column(controls=[header_row, banner], spacing=0, tight=True)

    def _build_hero_view(self, cfg: dict[str, Any]) -> ft.Control:
        theme = current_theme()
        greeting_name = self._current_greeting_name()

        if self._current_user:
            greeting_subtitle = "Continue your conversation with Nemis."
        else:
            greeting_subtitle = (
                "Ask about grades, enrollment, courses, requirements, or campus information."
            )

        return ft.Container(
            expand=True,
            alignment=ft.Alignment(0, 0),
            content=ft.Column(
                spacing=12,
                tight=True,
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Image(
                        src=LOGO_ASSET,
                        width=cfg["logo_size_hero"],
                        height=cfg["logo_size_hero"],
                        fit=ft.BoxFit.CONTAIN,
                    ),
                    ft.Text(
                        f"Hi {greeting_name}!",
                        size=cfg["font_size_hero_title"],
                        weight=ft.FontWeight.W_800,
                        color=theme.text_primary,
                        italic=True,
                    ),
                    ft.Text(
                        greeting_subtitle,
                        size=cfg["font_size_body"],
                        color=theme.text_secondary,
                        text_align=ft.TextAlign.CENTER,
                    ),
                    ft.Container(height=8),
                    ft.Row(
                        alignment=ft.MainAxisAlignment.CENTER,
                        spacing=8,
                        wrap=True,
                        controls=[
                            ft.Container(
                                padding=ft.Padding.symmetric(horizontal=14, vertical=9),
                                border_radius=18,
                                bgcolor=ft.Colors.with_opacity(0.10, theme.accent),
                                border=ft.Border.all(
                                    1,
                                    ft.Colors.with_opacity(0.24, theme.accent),
                                ),
                                content=ft.Text(
                                    label,
                                    color=theme.text_primary,
                                    size=cfg["chip_font_size"],
                                    weight=ft.FontWeight.W_600,
                                ),
                            )
                            for label in ("Grades", "Enrollment", "Courses")
                        ],
                    ),
                ],
            ),
        )

    def _build_message_list(self) -> ft.ListView:
        return ft.ListView(
            controls=[],
            expand=True,
            auto_scroll=False,
            build_controls_on_demand=False,
            spacing=12,
            padding=ft.Padding.only(top=8, bottom=8, left=4, right=4),
        )

    async def _deferred_scroll_to_latest(self) -> None:
        await asyncio.sleep(0.01)
        if self._message_list is None or not self._control_is_attached(self._message_list):
            return

        try:
            self._message_list.scroll_to(scroll_key="chat-bottom-anchor", duration=180)
        except Exception:
            return

        self._safe_update(self._message_list)

    def _request_scroll_to_latest(self) -> None:
        self._scroll_to_latest_requested = True

    def _build_chip(self, text: str, cfg: dict[str, Any]) -> ft.Control:
        theme = current_theme()
        return ft.Container(
            content=ft.Text(
                text,
                color=theme.text_primary,
                size=cfg["chip_font_size"],
                weight=ft.FontWeight.W_600,
            ),
            bgcolor=ft.Colors.with_opacity(0.28, theme.chip_bg),
            border_radius=18,
            border=ft.Border.all(1, ft.Colors.with_opacity(0.20, theme.border)),
            padding=ft.Padding.symmetric(horizontal=12, vertical=8),
            on_click=lambda _, value=text: self._send_message(value),
        )

    def _build_input_box(self, cfg: dict[str, Any]) -> ft.Container:
        theme = current_theme()

        self._input = ft.TextField(
            hint_text="Ask Nemis anything about NEMSU...",
            hint_style=ft.TextStyle(
                color=theme.text_muted,
                size=cfg["input_font_size"],
            ),
            border=ft.InputBorder.NONE,
            bgcolor=ft.Colors.TRANSPARENT,
            color=theme.text_primary,
            cursor_color=theme.accent,
            text_size=cfg["input_font_size"],
            expand=True,
            multiline=True,
            min_lines=1,
            max_lines=4 if self._is_mobile else 5,
            shift_enter=True,
            content_padding=ft.Padding.only(left=0, right=0, top=8, bottom=8),
            on_submit=self._handle_send,
        )

        button_size = cfg["button_height"] - 4
        self._send_button = ft.IconButton(
            icon=ft.Icons.ARROW_UPWARD_ROUNDED,
            icon_color=theme.text_primary,
            bgcolor=theme.send_btn,
            icon_size=18,
            width=button_size,
            height=button_size,
            tooltip="Send",
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=14),
                padding=ft.Padding.all(0),
            ),
            on_click=self._handle_send,
        )

        return ft.Container(
            bgcolor=ft.Colors.with_opacity(0.38, theme.input_bg),
            border_radius=24,
            border=ft.Border.all(1, ft.Colors.with_opacity(0.24, theme.border)),
            padding=ft.Padding.symmetric(
                horizontal=cfg["padding_card_h"] - 2,
                vertical=8 if self._is_mobile else 10,
            ),
            content=ft.Row(
                controls=[self._input, self._send_button],
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.END,
            ),
        )

    def _build_composer_section(self, cfg: dict[str, Any]) -> ft.Control:
        return ft.Column(
            spacing=12,
            controls=[
                self._build_input_box(cfg),
                ft.Row(
                    spacing=8,
                    scroll=ft.ScrollMode.AUTO,
                    controls=[self._build_chip(question, cfg) for question in SUGGESTED_QUESTIONS],
                ),
            ],
        )

    def _build_shell(self, cfg: dict[str, Any]) -> ft.Control:
        self._message_list = self._build_message_list()
        self._chat_host = ft.Container(expand=True, content=self._build_hero_view(cfg))

        body = ft.Column(
            expand=True,
            spacing=0,
            controls=[
                self._build_header(cfg),
                ft.Container(height=cfg["gap_header_body"]),
                ft.Container(content=self._chat_host, expand=True),
                ft.Container(height=cfg["gap_body_composer"]),
                self._build_composer_section(cfg),
            ],
        )

        return self._glass_card(
            body,
            padding=ft.Padding.symmetric(
                horizontal=cfg["padding_card_h"],
                vertical=cfg["padding_card_v"],
            ),
        )

    def _build_sidebar(self) -> SidebarPanel:
        current_id = self._history.current_conversation.id if self._history.current_conversation else None
        return SidebarPanel(
            expanded=self._sidebar_expanded,
            conversations=self._history.get_all_conversations(),
            current_conversation_id=current_id,
            is_mobile=self._is_mobile,
            on_toggle=self._toggle_sidebar,
            on_new_chat=self._handle_new_chat,
            on_select_conversation=self._load_conversation,
            on_history_secondary_tap=self._handle_history_secondary_tap,
            on_history_long_press=self._handle_history_long_press,
            on_settings=self._toggle_settings,
            on_show_splash=self._handle_show_splash,
            on_info=self._handle_info,
            on_feedback=self._handle_feedback,
        )

    def _build_theme_card(self, theme_key: str) -> ft.Control:
        active_theme = current_theme()
        palette = THEMES[theme_key]
        selected = theme_key == self._theme_name

        return ft.Container(
            border_radius=20,
            padding=ft.Padding.all(14),
            bgcolor=(
                ft.Colors.with_opacity(0.18, active_theme.accent)
                if selected
                else active_theme.sidebar_card
            ),
            border=ft.Border.all(
                1,
                ft.Colors.with_opacity(
                    0.30,
                    active_theme.accent if selected else active_theme.border,
                ),
            ),
            on_click=lambda _, name=theme_key: self._apply_theme(name),
            content=ft.Column(
                spacing=0,
                controls=[
                    ft.Row(
                        controls=[
                            ft.Text(
                                palette.name,
                                color=active_theme.text_primary,
                                size=13.5,
                                weight=ft.FontWeight.W_700,
                            ),
                            ft.Container(expand=True),
                            ft.Icon(
                                ft.Icons.CHECK_CIRCLE,
                                color=active_theme.accent,
                                size=18,
                                visible=selected,
                            ),
                        ]
                    ),
                    ft.Container(height=8),
                    ft.Row(
                        spacing=8,
                        controls=[
                            ft.Container(
                                width=18,
                                height=18,
                                border_radius=9,
                                bgcolor=color,
                            )
                            for color in (palette.grad_top, palette.grad_mid, palette.grad_bottom)
                        ],
                    ),
                ],
            ),
        )

    def _build_welcome_toggle_card(
        self,
        *,
        on_change: Callable[[ft.ControlEvent], None],
    ) -> ft.Control:
        theme = current_theme()

        return ft.Container(
            padding=ft.Padding.all(14),
            border_radius=20,
            bgcolor=theme.sidebar_card,
            border=ft.Border.all(1, ft.Colors.with_opacity(0.22, theme.border)),
            content=ft.Row(
                controls=[
                    ft.Checkbox(
                        value=should_show_splash(),
                        fill_color={ft.ControlState.SELECTED: theme.accent},
                        on_change=on_change,
                    ),
                    ft.Column(
                        expand=True,
                        spacing=4,
                        tight=True,
                        controls=[
                            ft.Text(
                                "Show welcome screen on launch",
                                size=13,
                                weight=ft.FontWeight.W_600,
                                color=theme.text_primary,
                            ),
                            ft.Text(
                                "Display the intro screen before opening chat.",
                                size=11,
                                color=theme.text_secondary,
                            ),
                        ],
                    ),
                ],
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.START,
            ),
        )

    def _build_settings_panel(self) -> ft.Container:
        theme = current_theme()

        inner = ft.Container(
            visible=False,
            expand=True,
            padding=ft.Padding.all(20),
            border_radius=28,
            bgcolor=theme.dialog_bg,
            border=ft.Border.all(1, ft.Colors.with_opacity(0.24, theme.border)),
            content=ft.Column(
                expand=True,
                spacing=10,
                controls=[
                    ft.Row(
                        controls=[
                            ft.Text(
                                "Settings",
                                size=24,
                                weight=ft.FontWeight.W_800,
                                color=theme.text_primary,
                            ),
                            ft.Container(expand=True),
                            ft.IconButton(
                                icon=ft.Icons.CLOSE_ROUNDED,
                                icon_color=theme.text_secondary,
                                on_click=self._toggle_settings,
                            ),
                        ]
                    ),
                    ft.Text(
                        "Choose a theme and tweak launch behavior.",
                        size=13,
                        color=theme.text_secondary,
                    ),
                    ft.Container(height=10),
                    ft.Text(
                        "Appearance",
                        size=12,
                        weight=ft.FontWeight.W_700,
                        color=theme.text_muted,
                    ),
                    ft.Column(
                        spacing=10,
                        controls=[self._build_theme_card(theme_key) for theme_key in THEMES],
                    ),
                    ft.Container(height=8),
                    ft.Text(
                        "Behavior",
                        size=12,
                        weight=ft.FontWeight.W_700,
                        color=theme.text_muted,
                    ),
                    self._build_welcome_toggle_card(on_change=self._handle_welcome_toggle),
                    ft.Container(expand=True),
                ],
            ),
        )

        return ft.Container(
            width=0,
            padding=ft.Padding.only(top=22, right=22, bottom=22),
            animate_size=ft.Animation(260, ft.AnimationCurve.EASE_IN_OUT_CUBIC),
            content=inner,
        )

    def _assemble(self) -> ft.Control:
        theme = current_theme()
        cfg = get_layout_config(self._page)

        shell = self._build_shell(cfg)
        outer_padding = ft.Padding.only(
            left=cfg["padding_horizontal"],
            right=cfg["padding_horizontal"],
            top=cfg["padding_vertical"] + cfg["top_padding"],
            bottom=cfg["padding_vertical"],
        )

        center = ft.Container(
            expand=True,
            padding=outer_padding,
            content=shell,
        )

        gradient_bg = ft.Container(
            expand=True,
            gradient=ft.LinearGradient(
                begin=ft.Alignment(-1, -1),
                end=ft.Alignment(1, 1),
                colors=[theme.grad_top, theme.grad_mid, theme.grad_bottom],
            ),
        )

        if self._is_mobile:
            drawer_width = cfg["drawer_width"]
            drawer = self._build_custom_drawer(cfg)

            self._mobile_backdrop = ft.Container(
                expand=True,
                visible=self._custom_drawer_open,
                bgcolor=ft.Colors.with_opacity(0.42, "#000000"),
                on_click=self._close_drawer,
            )
            self._mobile_drawer_container = ft.Container(
                width=drawer_width,
                left=0 if self._custom_drawer_open else -drawer_width,
                top=0,
                bottom=0,
                animate_position=ft.Animation(260, ft.AnimationCurve.EASE_IN_OUT_CUBIC),
                bgcolor=ft.Colors.TRANSPARENT,
                content=drawer,
            )

            return ft.Stack(
                expand=True,
                controls=[
                    gradient_bg,
                    center,
                    self._mobile_backdrop,
                    self._mobile_drawer_container,
                ],
            )

        self._sidebar_host = ft.Container(
            width=_SIDEBAR_EXPANDED_WIDTH if self._sidebar_expanded else _SIDEBAR_COLLAPSED_WIDTH,
            animate_size=ft.Animation(260, ft.AnimationCurve.EASE_IN_OUT_CUBIC),
            content=self._build_sidebar(),
        )
        self._settings_panel = self._build_settings_panel()

        return ft.Stack(
            expand=True,
            controls=[
                gradient_bg,
                ft.Container(
                    expand=True,
                    content=ft.Row(
                        controls=[self._sidebar_host, center, self._settings_panel],
                        spacing=0,
                        expand=True,
                        vertical_alignment=ft.CrossAxisAlignment.STRETCH,
                    ),
                ),
            ],
        )

    # Account handlers

    def _handle_account(self, e=None) -> None:
        AccountDialog(
            page=self._page,
            current_user=self._current_user,
            is_mobile=self._is_mobile,
            on_login=self._handle_login,
            on_logout=self._handle_logout,
            on_guest=self._handle_guest_continue,
            on_user_update=self._handle_user_update,
        ).open()

    def _handle_login(self, user: UserInfo) -> None:
        self._dismiss_history_context_menu()
        self._dismiss_history_delete_sheet()
        self._current_user = user
        self._cancel_pending_chat_request()
        self._reset_session_greeting_name()
        self._set_theme_runtime(self._resolved_theme_name(user))
        user_id = user["user_id"]

        def _background_work() -> None:
            profile = api_client.load_user_profile(user_id) or user

            self._history.reload(user_id)

            async def _apply_on_ui() -> None:
                self._current_user = profile
                self._set_theme_runtime(self._resolved_theme_name(profile))

                self._history.current_conversation = None
                self._history.new_conversation()
                self._clear_input()

                banner_message = (
                    "Logged in. Fresh new chat ready; your past conversations are in the sidebar."
                    if self._history.conversations
                    else "Logged in. Start your first conversation."
                )

                self._refresh()
                self._safe_update(self)
                self._render_conversation()
                self._refresh_sidebar()
                self._show_auth_banner(banner_message, "success")

            self._page.run_task(_apply_on_ui)

        self._run_in_thread(_background_work)

    def _handle_logout(self) -> None:
        self._dismiss_history_context_menu()
        self._dismiss_history_delete_sheet()
        self._current_user = None
        self._cancel_pending_chat_request()
        self._reset_session_greeting_name()
        self._set_theme_runtime(DEFAULT_THEME)

        self._history.reload(None)
        self._history.new_conversation()
        self._clear_input()

        self._refresh()
        self._safe_update(self)
        self._refresh_sidebar()
        self._show_auth_banner(
            "Signed out successfully. Continuing as guest.",
            "success",
        )

    def _handle_guest_continue(self) -> None:
        self._dismiss_history_context_menu()
        self._dismiss_history_delete_sheet()
        if self._current_user is None:
            self._reset_session_greeting_name()
        self._show_auth_banner("Continuing as guest.", "success")

    def _handle_user_update(self, user: UserInfo) -> None:
        self._current_user = user
        self._set_theme_runtime(self._resolved_theme_name(user))
        self._refresh()
        self._safe_update(self)
        self._safe_page_update()
        self._refresh_sidebar()

    # Message flow

    def _handle_send(self, e=None) -> None:
        text = (self._input.value or "").strip() if self._input else ""
        if text:
            self._send_message(text)

    def _unlock_input(self) -> None:
        self._sending = False
        self._pending_request_session_id = None
        self._typing_session_id = None
        self._set_send_enabled(True)
        self._safe_page_update()

    def _send_message(self, text: str) -> None:
        if self._sending:
            return

        self._sending = True
        self._clear_input()

        self._history.add_message("user", text)

        current_conversation = self._history.current_conversation
        if current_conversation is None:
            self._unlock_input()
            return

        session_id = current_conversation.id
        user_id = self._current_user["user_id"] if self._current_user else None

        self._pending_request_session_id = session_id
        self._typing_session_id = session_id
        self._request_scroll_to_latest()
        self._clear_inline_error(session_id)
        self._render_conversation()
        self._set_send_enabled(False)

        try:
            api_client.send_message(
                session_id=session_id,
                messages=self._history.get_chat_messages(),
                on_response=lambda response: self._on_response(response, session_id),
                on_error=lambda error: self._on_error(error, session_id),
                user_id=user_id,
            )
        except Exception:
            self._typing_session_id = None
            self._unlock_input()

    def _on_response(self, response: str, session_id: str) -> None:
        if self._pending_request_session_id != session_id:
            return

        self._clear_inline_error(session_id)
        self._typing_session_id = None
        self._request_scroll_to_latest()
        message = self._append_message_to_conversation(session_id, "assistant", response)
        if message is None:
            self._unlock_input()
            return

        if self._history.current_conversation is not None and self._history.current_conversation.id == session_id:
            self._render_conversation()
        self._refresh_sidebar()
        self._unlock_input()

    def _on_error(self, error: str, session_id: str) -> None:
        if self._pending_request_session_id != session_id:
            return

        self._typing_session_id = None
        self._inline_error = (session_id, error)
        self._request_scroll_to_latest()
        if self._history.current_conversation is not None and self._history.current_conversation.id == session_id:
            self._render_conversation()
        self._unlock_input()

    # Conversation / sidebar

    def _refresh_sidebar(self) -> None:
        if self._is_mobile:
            if self._mobile_drawer_container is None:
                return
            if not self._control_is_attached(self._mobile_drawer_container):
                return

            cfg = get_layout_config(self._page)
            self._mobile_drawer_container.width = cfg["drawer_width"]
            self._mobile_drawer_container.content = self._build_custom_drawer(cfg)
            self._mobile_drawer_container.left = (
                0 if self._custom_drawer_open else -cfg["drawer_width"]
            )
            self._safe_update(self._mobile_drawer_container)
            return

        if self._sidebar_host is None:
            return

        if not self._control_is_attached(self._sidebar_host):
            return

        self._sidebar_host.width = (
            _SIDEBAR_EXPANDED_WIDTH if self._sidebar_expanded else _SIDEBAR_COLLAPSED_WIDTH
        )
        self._sidebar_host.content = self._build_sidebar()
        self._safe_update(self._sidebar_host)

    def _render_conversation(self) -> None:
        conversation = self._history.current_conversation
        if self._message_list is None or self._chat_host is None:
            return

        self._message_list.controls.clear()
        has_content = bool(conversation and any((message.content or "").strip() for message in conversation.messages))

        if has_content and conversation is not None:
            for message in conversation.messages:
                if not (message.content or "").strip():
                    continue
                if message.role == "user":
                    self._message_list.controls.append(user_bubble(message.content, message.timestamp))
                else:
                    self._message_list.controls.append(assistant_bubble(message.content, message.timestamp))

            if self._inline_error and self._inline_error[0] == conversation.id:
                theme = current_theme()
                self._message_list.controls.append(
                    ft.Container(
                        padding=ft.Padding.all(12),
                        border_radius=18,
                        bgcolor=ft.Colors.with_opacity(0.10, theme.error),
                        border=ft.Border.all(1, ft.Colors.with_opacity(0.32, theme.error)),
                        content=ft.Text(
                            self._inline_error[1],
                            color=theme.text_primary,
                            size=13,
                        ),
                    )
                )

            if self._typing_session_id == conversation.id:
                self._message_list.controls.append(typing_indicator())

            self._message_list.controls.append(self._chat_bottom_anchor)
            self._chat_host.content = self._message_list
        else:
            cfg = get_layout_config(self._page)
            self._hero_view = self._build_hero_view(cfg)
            self._chat_host.content = self._hero_view

        self._safe_update(self._chat_host)
        self._safe_update(self._message_list)
        self._safe_page_update()
        if has_content and self._scroll_to_latest_requested:
            self._scroll_to_latest_requested = False
            self._page.run_task(self._deferred_scroll_to_latest)
        self._refresh_sidebar()

    def _toggle_sidebar(self, e=None) -> None:
        if self._is_mobile:
            return
        self._sidebar_expanded = not self._sidebar_expanded
        self._refresh_sidebar()
        self._safe_update(self)

    def _load_conversation(self, conversation_id: str) -> None:
        self._dismiss_history_context_menu()
        self._dismiss_history_delete_sheet()
        if self._history.switch_conversation(conversation_id):
            self._request_scroll_to_latest()
            self._render_conversation()

    def _handle_new_chat(self, e=None) -> None:
        self._dismiss_history_context_menu()
        self._dismiss_history_delete_sheet()
        self._auth_banner = None
        self._cancel_pending_chat_request()
        self._history.current_conversation = None
        self._history.new_conversation()
        self._clear_input()
        self._render_conversation()

    # Misc handlers

    def _dismiss_history_context_menu(self, e=None) -> None:
        overlay = self._history_context_menu_overlay
        self._history_context_menu_overlay = None
        self._remove_overlay_control(overlay)

    def _dismiss_history_delete_sheet(self, e=None) -> None:
        sheet = self._history_delete_sheet
        self._history_delete_sheet = None
        if sheet is None:
            return

        try:
            sheet.open = False
        except Exception:
            pass

        self._safe_page_update()
        self._remove_overlay_control(sheet)

    def _handle_history_secondary_tap(self, conversation_id: str, position: Any) -> None:
        if self._is_mobile:
            return
        self._dismiss_history_delete_sheet()
        self._show_history_context_menu(conversation_id, position)

    def _handle_history_long_press(self, conversation_id: str) -> None:
        if not self._is_mobile:
            return
        self._dismiss_history_context_menu()
        self._show_history_delete_sheet(conversation_id)

    def _show_history_context_menu(self, conversation_id: str, position: Any) -> None:
        self._dismiss_history_context_menu()
        theme = current_theme()

        page_width = self._page_width()
        page_height = float(self._page.height or 860)
        menu_width = 208.0
        menu_height = 56.0
        raw_x = float(getattr(position, "x", 20.0) or 20.0)
        raw_y = float(getattr(position, "y", 20.0) or 20.0)
        left = min(max(raw_x, 12.0), max(12.0, page_width - menu_width - 12.0))
        top = min(max(raw_y, 12.0), max(12.0, page_height - menu_height - 12.0))

        def delete_now(e=None) -> None:
            self._dismiss_history_context_menu()
            self._delete_conversation(conversation_id)

        menu_card = ft.Container(
            width=menu_width,
            bgcolor=theme.dialog_bg,
            border_radius=18,
            border=ft.Border.all(1, ft.Colors.with_opacity(0.24, theme.border)),
            shadow=ft.BoxShadow(
                blur_radius=24,
                offset=ft.Offset(0, 12),
                color=ft.Colors.with_opacity(0.28, theme.shadow),
            ),
            content=ft.Container(
                padding=ft.Padding.symmetric(horizontal=14, vertical=12),
                border_radius=18,
                on_click=delete_now,
                content=ft.Row(
                    controls=[
                        ft.Icon(
                            ft.Icons.DELETE_OUTLINE_ROUNDED,
                            size=18,
                            color=theme.error,
                        ),
                        ft.Text(
                            "Delete conversation",
                            size=12.5,
                            weight=ft.FontWeight.W_600,
                            color=theme.text_primary,
                        ),
                    ],
                    spacing=10,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
            ),
        )

        overlay = ft.Stack(
            expand=True,
            clip_behavior=ft.ClipBehavior.NONE,
            controls=[
                ft.GestureDetector(
                    on_tap=self._dismiss_history_context_menu,
                    on_secondary_tap=self._dismiss_history_context_menu,
                    content=ft.Container(
                        width=page_width,
                        height=page_height,
                        bgcolor=ft.Colors.with_opacity(0.001, "#000000"),
                    ),
                ),
                ft.Container(
                    left=left,
                    top=top,
                    content=ft.GestureDetector(
                        on_tap=lambda _: None,
                        on_secondary_tap=lambda _: None,
                        content=menu_card,
                    ),
                ),
            ],
        )

        self._history_context_menu_overlay = overlay
        self._append_overlay_control(overlay)

    def _show_history_delete_sheet(self, conversation_id: str) -> None:
        self._dismiss_history_delete_sheet()
        theme = current_theme()

        def dismiss(e=None) -> None:
            self._dismiss_history_delete_sheet()

        def confirm_delete(e=None) -> None:
            self._dismiss_history_delete_sheet()
            self._delete_conversation(conversation_id)

        sheet = ft.BottomSheet(
            bgcolor=theme.dialog_bg,
            dismissible=True,
            show_drag_handle=True,
            shape=ft.RoundedRectangleBorder(radius=28),
            barrier_color=ft.Colors.with_opacity(0.32, "#000000"),
            on_dismiss=lambda _: self._dismiss_history_delete_sheet(),
            content=ft.Container(
                padding=ft.Padding.from_ltrb(20, 8, 20, 24),
                content=ft.Column(
                    tight=True,
                    spacing=18,
                    controls=[
                        ft.Text(
                            "Delete this conversation?",
                            size=16,
                            weight=ft.FontWeight.W_700,
                            color=theme.text_primary,
                        ),
                        ft.Row(
                            spacing=10,
                            controls=[
                                ft.TextButton(
                                    "Dismiss",
                                    on_click=dismiss,
                                    style=ft.ButtonStyle(color=theme.text_muted),
                                ),
                                ft.Container(expand=True),
                                ft.Button(
                                    content=ft.Text(
                                        "Delete",
                                        color=theme.text_primary,
                                        weight=ft.FontWeight.W_700,
                                    ),
                                    style=ft.ButtonStyle(
                                        bgcolor=ft.Colors.with_opacity(0.14, theme.error),
                                        side=ft.BorderSide(1, ft.Colors.with_opacity(0.30, theme.error)),
                                        shape=ft.RoundedRectangleBorder(radius=14),
                                        elevation=0,
                                        padding=ft.Padding.symmetric(horizontal=18, vertical=12),
                                    ),
                                    on_click=confirm_delete,
                                ),
                            ],
                        ),
                    ],
                ),
            ),
        )

        self._history_delete_sheet = sheet
        self._append_overlay_control(sheet)
        sheet.open = True
        self._safe_page_update()

    def _delete_conversation(self, conversation_id: str) -> None:
        self._dismiss_history_context_menu()

        was_current = (
            self._history.current_conversation is not None
            and self._history.current_conversation.id == conversation_id
        )
        deleted = self._history.delete_conversation(conversation_id)
        if not deleted:
            return

        if self._pending_request_session_id == conversation_id or self._typing_session_id == conversation_id:
            self._cancel_pending_chat_request()
        self._clear_inline_error(conversation_id)

        if was_current:
            replacement = self._history.activate_most_recent_conversation()
            if replacement is None:
                self._history.new_conversation()
                self._clear_input()

        self._refresh()
        self._safe_update(self)
        self._refresh_sidebar()

        user_id = str((self._current_user or {}).get("user_id", "")).strip()
        if user_id:
            self._run_in_thread(
                lambda: self._delete_conversation_from_backend(user_id, conversation_id)
            )

    def _delete_conversation_from_backend(self, user_id: str, conversation_id: str) -> None:
        deleted = api_client.delete_conversation(conversation_id, user_id)
        if deleted:
            return

        current_id = self._history.current_conversation.id if self._history.current_conversation else None

        async def _restore() -> None:
            if not self._current_user or self._current_user.get("user_id") != user_id:
                return

            self._history.reload(user_id)
            if current_id and not self._history.switch_conversation(current_id):
                restored = self._history.activate_most_recent_conversation()
                if restored is None:
                    self._history.new_conversation()

            self._refresh()
            self._safe_update(self)
            self._refresh_sidebar()
            self._show_auth_banner("Unable to delete conversation right now.", "error")

        self._page.run_task(_restore)

    def _handle_welcome_toggle(self, event: ft.ControlEvent) -> None:
        set_show_splash(bool(event.control.value))

    def _handle_show_splash(self, e=None) -> None:
        set_show_splash(True)
        self._custom_drawer_open = False

        def open_chat_again() -> None:
            self._page.clean()
            self._page.add(ChatPage(self._page))
            self._safe_page_update()

        self._page.clean()
        self._page.add(SplashPage(self._page, on_continue=open_chat_again))
        self._safe_page_update()

    def _open_dialog(self, dialog: ft.AlertDialog) -> None:
        self._page.overlay.append(dialog)
        dialog.open = True
        self._safe_page_update()

    def _handle_info(self, e=None) -> None:
        theme = current_theme()
        dialog_ref = ft.Ref[ft.AlertDialog]()

        def close(e=None) -> None:
            if dialog_ref.current is not None:
                dialog_ref.current.open = False
            self._safe_page_update()

        provider_value = self._provider_label
        if self._provider_model:
            provider_value = f"{provider_value} ({self._provider_model})"

        rows = [
            ("System", "Nemorax / Nemis"),
            ("Purpose", "Campus assistant for NEMSU"),
            ("Provider", provider_value),
            ("Backend", "FastAPI"),
            ("Scope", "NEMSU-related questions only"),
        ]

        dialog = ft.AlertDialog(
            ref=dialog_ref,
            bgcolor=theme.dialog_bg,
            shape=ft.RoundedRectangleBorder(radius=24),
            title=ft.Text(
                "About Nemis",
                color=theme.text_primary,
                weight=ft.FontWeight.W_800,
            ),
            content=ft.Container(
                width=360,
                padding=ft.Padding.all(4),
                content=ft.Column(
                    spacing=10,
                    tight=True,
                    controls=[
                        ft.Row(
                            controls=[
                                ft.Text(
                                    label,
                                    color=theme.text_muted,
                                    size=12,
                                    width=82,
                                ),
                                ft.Text(
                                    value,
                                    color=theme.text_primary,
                                    size=12.5,
                                    expand=True,
                                ),
                            ]
                        )
                        for label, value in rows
                    ],
                ),
            ),
            actions=[
                ft.TextButton(
                    "Close",
                    on_click=close,
                    style=ft.ButtonStyle(color=theme.accent),
                )
            ],
        )
        self._open_dialog(dialog)

    def _handle_feedback(self, e=None) -> None:
        theme = current_theme()
        dialog_ref = ft.Ref[ft.AlertDialog]()

        feedback_box = ft.TextField(
            hint_text="Tell us what to improve...",
            hint_style=ft.TextStyle(color=theme.text_muted),
            multiline=True,
            min_lines=4,
            max_lines=6,
            bgcolor=theme.surface_alt,
            color=theme.text_primary,
            border_radius=16,
            border_color=ft.Colors.with_opacity(0.24, theme.border),
        )

        def close(e=None) -> None:
            if dialog_ref.current is not None:
                dialog_ref.current.open = False
            self._safe_page_update()

        def submit(e=None) -> None:
            comment = (feedback_box.value or "").strip()
            close()

            session_id = (
                self._history.current_conversation.id
                if self._history.current_conversation
                else None
            )
            user_id = self._current_user["user_id"] if self._current_user else None

            self._run_in_thread(
                lambda: api_client.submit_feedback(
                    comment,
                    session_id=session_id,
                    user_id=user_id,
                )
            )

            self._page.snack_bar = ft.SnackBar(
                bgcolor=theme.send_btn,
                content=ft.Text(
                    "Thanks for your feedback.",
                    color=theme.text_primary,
                ),
            )
            self._page.snack_bar.open = True
            self._safe_page_update()

        dialog = ft.AlertDialog(
            ref=dialog_ref,
            bgcolor=theme.dialog_bg,
            shape=ft.RoundedRectangleBorder(radius=24),
            title=ft.Text(
                "Feedback",
                color=theme.text_primary,
                weight=ft.FontWeight.W_800,
            ),
            content=ft.Container(width=380, content=feedback_box),
            actions=[
                ft.TextButton(
                    "Cancel",
                    on_click=close,
                    style=ft.ButtonStyle(color=theme.text_muted),
                ),
                ft.Button(
                    content=ft.Text(
                        "Submit",
                        color="#081018",
                        weight=ft.FontWeight.W_700,
                    ),
                    style=ft.ButtonStyle(
                        bgcolor=theme.accent,
                        shape=ft.RoundedRectangleBorder(radius=14),
                        elevation=0,
                    ),
                    on_click=submit,
                ),
            ],
        )
        self._open_dialog(dialog)



