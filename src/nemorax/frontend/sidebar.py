"""Collapsible navigation sidebar for Nemorax."""
from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any

import flet as ft

from nemorax.frontend.config import APP_NAME, BRAND_NAME, LOGO_ASSET, current_theme
from nemorax.frontend.history_service import Conversation
from nemorax.frontend.time_utils import ph_now


SIDEBAR_WIDTH_EXPANDED = 272
SIDEBAR_WIDTH_COLLAPSED = 76
_HEADER_HEIGHT = 52
_HISTORY_LIMIT = 10
_NAV_BUTTON_HEIGHT = 48
_HISTORY_ICON_SIZE = 18
_NAV_ICON_SIZE = 20
_TOGGLE_BUTTON_SIZE = 44


class SidebarPanel(ft.Container):
    def __init__(
        self,
        *,
        expanded: bool,
        conversations: list[Conversation],
        current_conversation_id: str | None,
        is_mobile: bool,
        on_toggle: Callable[..., None],
        on_new_chat: Callable[..., None],
        on_select_conversation: Callable[[str], None],
        on_history_secondary_tap: Callable[[str, Any], None],
        on_history_long_press: Callable[[str], None],
        on_settings: Callable[..., None],
        on_show_splash: Callable[..., None],
        on_info: Callable[..., None],
        on_feedback: Callable[..., None],
    ) -> None:
        super().__init__()
        theme = current_theme()

        self.expanded = expanded
        self.conversations = conversations
        self.current_conversation_id = current_conversation_id
        self.is_mobile = is_mobile
        self.on_toggle = on_toggle
        self.on_new_chat = on_new_chat
        self.on_select_conversation = on_select_conversation
        self.on_history_secondary_tap = on_history_secondary_tap
        self.on_history_long_press = on_history_long_press
        self.on_settings = on_settings
        self.on_show_splash = on_show_splash
        self.on_info = on_info
        self.on_feedback = on_feedback

        self.width = SIDEBAR_WIDTH_EXPANDED if expanded else SIDEBAR_WIDTH_COLLAPSED
        self.bgcolor = theme.sidebar_bg
        self.padding = ft.Padding.symmetric(vertical=16, horizontal=10)
        self.border = ft.Border.only(
            right=ft.BorderSide(1, ft.Colors.with_opacity(0.16, theme.border))
        )
        self.animate_size = ft.Animation(260, ft.AnimationCurve.EASE_IN_OUT_CUBIC)
        self.content = self._build()

    def _toggle_button(self, tooltip: str) -> ft.IconButton:
        theme = current_theme()
        return ft.IconButton(
            icon=ft.Icons.MENU_ROUNDED,
            icon_color=theme.accent,
            tooltip=tooltip,
            width=_TOGGLE_BUTTON_SIZE,
            height=_TOGGLE_BUTTON_SIZE,
            style=ft.ButtonStyle(
                bgcolor=ft.Colors.with_opacity(0.10, theme.accent),
                shape=ft.RoundedRectangleBorder(radius=16),
            ),
            on_click=self.on_toggle,
        )

    def _nav_body(
        self,
        *,
        icon: ft.IconData,
        label: str,
        accent: bool,
    ) -> ft.Row:
        theme = current_theme()

        controls: list[ft.Control] = [
            ft.Icon(
                icon,
                size=_NAV_ICON_SIZE,
                color=theme.accent if accent else theme.text_secondary,
            )
        ]
        if self.expanded:
            controls.append(
                ft.Text(
                    label,
                    size=13,
                    weight=ft.FontWeight.W_600,
                    color=theme.text_primary,
                )
            )

        return ft.Row(
            controls=controls,
            spacing=12,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            alignment=(
                ft.MainAxisAlignment.START
                if self.expanded
                else ft.MainAxisAlignment.CENTER
            ),
        )

    def _build_nav_button(
        self,
        icon: ft.IconData,
        label: str,
        handler: Callable[..., None],
        *,
        accent: bool = False,
    ) -> ft.Control:
        theme = current_theme()

        return ft.Container(
            height=_NAV_BUTTON_HEIGHT,
            alignment=ft.Alignment(-1 if self.expanded else 0, 0),
            content=self._nav_body(icon=icon, label=label, accent=accent),
            tooltip=label if not self.expanded else None,
            padding=ft.Padding.symmetric(horizontal=12, vertical=12),
            border_radius=18,
            bgcolor=ft.Colors.with_opacity(0.10, theme.accent) if accent else None,
            border=ft.Border.all(
                1,
                ft.Colors.with_opacity(
                    0.20,
                    theme.accent if accent else theme.border,
                ),
            ),
            on_click=handler,
        )

    def _history_subtitle(self, conversation: Conversation) -> str:
        if conversation.is_placeholder:
            return "Ready to type"

        stamp = conversation.updated_at
        today = ph_now().date()

        if stamp.date() == today:
            return stamp.strftime("Today - %I:%M %p").replace(" 0", " ")
        if stamp.date() == today - timedelta(days=1):
            return stamp.strftime("Yesterday - %I:%M %p").replace(" 0", " ")

        return stamp.strftime("%b %d - %I:%M %p").replace(" 0", " ")

    def _history_icon(self, conversation: Conversation) -> ft.IconData:
        return (
            ft.Icons.EDIT_SQUARE
            if conversation.is_placeholder
            else ft.Icons.CHAT_BUBBLE_OUTLINE_ROUNDED
        )

    def _build_collapsed_history_item(
        self,
        conversation: Conversation,
        *,
        selected: bool,
        icon_data: ft.IconData,
    ) -> ft.Control:
        theme = current_theme()

        return ft.Container(
            tooltip=conversation.title,
            width=52,
            height=52,
            border_radius=16,
            alignment=ft.Alignment(0, 0),
            bgcolor=(
                ft.Colors.with_opacity(0.18, theme.accent)
                if selected
                else theme.sidebar_card
            ),
            border=ft.Border.all(
                1,
                ft.Colors.with_opacity(
                    0.24,
                    theme.accent if selected else theme.border,
                ),
            ),
            content=ft.Icon(
                icon_data,
                color=theme.text_primary,
                size=_HISTORY_ICON_SIZE,
            ),
        )

    def _build_expanded_history_item(
        self,
        conversation: Conversation,
        *,
        selected: bool,
        icon_data: ft.IconData,
        subtitle: str,
    ) -> ft.Control:
        theme = current_theme()

        return ft.Container(
            bgcolor=(
                ft.Colors.with_opacity(0.14, theme.accent)
                if selected
                else theme.sidebar_card
            ),
            border_radius=16,
            padding=ft.Padding.symmetric(horizontal=12, vertical=10),
            border=ft.Border.all(
                1,
                ft.Colors.with_opacity(
                    0.24,
                    theme.accent if selected else theme.border,
                ),
            ),
            content=ft.Row(
                controls=[
                    ft.Icon(
                        icon_data,
                        color=theme.accent if selected else theme.text_secondary,
                        size=_HISTORY_ICON_SIZE,
                    ),
                    ft.Column(
                        controls=[
                            ft.Text(
                                conversation.title,
                                color=theme.text_primary,
                                size=12.5,
                                weight=ft.FontWeight.W_600,
                                max_lines=1,
                                overflow=ft.TextOverflow.ELLIPSIS,
                            ),
                            ft.Text(
                                subtitle,
                                color=theme.text_muted,
                                size=10.5,
                            ),
                        ],
                        spacing=3,
                        expand=True,
                    ),
                ],
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )

    def _build_history_item(self, conversation: Conversation) -> ft.Control:
        selected = conversation.id == self.current_conversation_id
        subtitle = self._history_subtitle(conversation)
        icon_data = self._history_icon(conversation)

        if not self.expanded:
            item = self._build_collapsed_history_item(
                conversation,
                selected=selected,
                icon_data=icon_data,
            )
        else:
            item = self._build_expanded_history_item(
                conversation,
                selected=selected,
                icon_data=icon_data,
                subtitle=subtitle,
            )

        return ft.GestureDetector(
            mouse_cursor=ft.MouseCursor.CLICK,
            on_tap=lambda _, conversation_id=conversation.id: self.on_select_conversation(conversation_id),
            on_secondary_tap_down=(
                None
                if self.is_mobile or conversation.is_placeholder
                else (
                    lambda event, conversation_id=conversation.id: self.on_history_secondary_tap(
                        conversation_id,
                        event.global_position,
                    )
                )
            ),
            on_long_press=(
                None
                if (not self.is_mobile) or conversation.is_placeholder
                else lambda _, conversation_id=conversation.id: self.on_history_long_press(conversation_id)
            ),
            content=item,
        )

    def _build_history(self) -> ft.Control:
        theme = current_theme()

        if not self.conversations:
            if self.expanded:
                return ft.Container(
                    padding=ft.Padding.only(top=10, left=4, right=4),
                    content=ft.Text(
                        "No conversations yet.",
                        color=theme.text_muted,
                        size=12,
                    ),
                )
            return ft.Container()

        return ft.ListView(
            controls=[
                self._build_history_item(conversation)
                for conversation in self.conversations[:_HISTORY_LIMIT]
            ],
            spacing=8,
            expand=True,
            auto_scroll=False,
        )

    def _build_expanded_header(self) -> ft.Control:
        theme = current_theme()

        return ft.Container(
            height=_HEADER_HEIGHT,
            content=ft.Row(
                controls=[
                    ft.Image(
                        src=LOGO_ASSET,
                        width=32,
                        height=32,
                        fit=ft.BoxFit.CONTAIN,
                    ),
                    ft.Column(
                        controls=[
                            ft.Text(
                                APP_NAME,
                                color=theme.text_primary,
                                size=14,
                                weight=ft.FontWeight.W_700,
                            ),
                            ft.Text(
                                f"AI assistant by {BRAND_NAME}",
                                color=theme.text_muted,
                                size=10.5,
                            ),
                        ],
                        spacing=0,
                    ),
                    ft.Container(expand=True),
                    self._toggle_button("Collapse sidebar"),
                ],
                alignment=ft.MainAxisAlignment.START,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )

    def _build_collapsed_header(self) -> ft.Control:
        return ft.Container(
            height=_HEADER_HEIGHT,
            alignment=ft.Alignment(0, 0),
            content=self._toggle_button("Expand sidebar"),
        )

    def _build_header(self) -> ft.Control:
        return (
            self._build_expanded_header()
            if self.expanded
            else self._build_collapsed_header()
        )

    def _build_history_header(self) -> ft.Control:
        theme = current_theme()
        return ft.Row(
            controls=[
                ft.Text(
                    "Recent chats",
                    size=11,
                    weight=ft.FontWeight.W_700,
                    color=theme.text_muted,
                )
            ],
            visible=self.expanded,
        )

    def _build(self) -> ft.Control:
        return ft.Column(
            controls=[
                self._build_header(),
                ft.Container(height=16),
                self._build_nav_button(
                    ft.Icons.ADD_ROUNDED,
                    "New chat",
                    self.on_new_chat,
                    accent=True,
                ),
                ft.Container(height=8),
                self._build_nav_button(
                    ft.Icons.TUNE_ROUNDED,
                    "Settings",
                    self.on_settings,
                ),
                self._build_nav_button(
                    ft.Icons.CARD_TRAVEL_ROUNDED,
                    "Show welcome",
                    self.on_show_splash,
                ),
                ft.Container(height=18),
                self._build_history_header(),
                ft.Container(content=self._build_history(), expand=True),
                ft.Container(height=8),
                self._build_nav_button(
                    ft.Icons.INFO_OUTLINE_ROUNDED,
                    "About",
                    self.on_info,
                ),
                self._build_nav_button(
                    ft.Icons.RATE_REVIEW_OUTLINED,
                    "Feedback",
                    self.on_feedback,
                ),
            ],
            spacing=6,
            expand=True,
        )

