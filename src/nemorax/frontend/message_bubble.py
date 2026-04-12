"""Reusable chat bubble controls."""
from __future__ import annotations

from datetime import datetime

import flet as ft

from nemorax.frontend.config import CHATBOT_NAME, current_theme
from nemorax.frontend.time_utils import PH_TZ


_BUBBLE_TEXT_SIZE = 14
_META_TEXT_SIZE = 11
_AVATAR_SIZE = 34
_AVATAR_RADIUS = 17
_ROW_SPACING = 10
_META_SPACING = 5
_USER_BUBBLE_RADIUS = (22, 22, 22, 6)
_BOT_BUBBLE_RADIUS = (6, 22, 22, 22)
_TYPING_BUBBLE_RADIUS = (6, 18, 18, 18)


def _bubble_shadow() -> ft.BoxShadow:
    theme = current_theme()
    return ft.BoxShadow(
        spread_radius=0,
        blur_radius=18,
        color=ft.Colors.with_opacity(0.20, theme.shadow),
        offset=ft.Offset(0, 8),
    )


def _time_label(timestamp: datetime | None) -> str:
    if timestamp is None:
        return ""
    if timestamp.tzinfo is not None:
        timestamp = timestamp.astimezone(PH_TZ)
    return timestamp.strftime("%I:%M %p").lstrip("0")


def _bubble_border_radius(
    top_left: int,
    top_right: int,
    bottom_left: int,
    bottom_right: int,
) -> ft.BorderRadius:
    return ft.BorderRadius.only(
        top_left=top_left,
        top_right=top_right,
        bottom_left=bottom_left,
        bottom_right=bottom_right,
    )


def _meta_text(label: str, *, color: str, weight: ft.FontWeight) -> ft.Text:
    return ft.Text(
        label,
        color=color,
        size=_META_TEXT_SIZE,
        weight=weight,
    )


def _message_text(text: str, *, color: str) -> ft.Text:
    return ft.Text(
        text,
        color=color,
        size=_BUBBLE_TEXT_SIZE,
        selectable=True,
    )


def _avatar() -> ft.Container:
    theme = current_theme()
    return ft.Container(
        width=_AVATAR_SIZE,
        height=_AVATAR_SIZE,
        border_radius=_AVATAR_RADIUS,
        bgcolor=theme.accent,
        alignment=ft.Alignment(0, 0),
        shadow=ft.BoxShadow(
            blur_radius=12,
            color=ft.Colors.with_opacity(0.22, theme.accent),
            offset=ft.Offset(0, 4),
        ),
        content=ft.Text(
            CHATBOT_NAME[:1].upper(),
            color="#081018",
            size=14,
            weight=ft.FontWeight.W_800,
        ),
    )


def _bubble_container(
    *,
    text: str,
    bgcolor: str,
    text_color: str,
    border_color: str,
    radius: tuple[int, int, int, int],
    padding: ft.Padding,
) -> ft.Container:
    return ft.Container(
        expand=True,
        content=_message_text(text, color=text_color),
        bgcolor=bgcolor,
        border_radius=_bubble_border_radius(*radius),
        padding=padding,
        shadow=_bubble_shadow(),
        border=ft.Border.all(1, border_color),
    )


def user_bubble(text: str, timestamp: datetime | None = None) -> ft.Row:
    theme = current_theme()
    meta_label = f"You - {_time_label(timestamp)}" if timestamp else "You"

    bubble = _bubble_container(
        text=text,
        bgcolor=theme.user_bubble,
        text_color=theme.text_primary,
        border_color=ft.Colors.with_opacity(0.18, theme.text_primary),
        radius=_USER_BUBBLE_RADIUS,
        padding=ft.Padding.symmetric(horizontal=16, vertical=12),
    )

    return ft.Row(
        controls=[
            ft.Container(expand=True),
            ft.Container(
                expand=4,
                content=ft.Column(
                    controls=[
                        _meta_text(
                            meta_label,
                            color=theme.text_muted,
                            weight=ft.FontWeight.W_600,
                        ),
                        bubble,
                    ],
                    spacing=_META_SPACING,
                    horizontal_alignment=ft.CrossAxisAlignment.END,
                    tight=True,
                ),
            ),
        ],
        spacing=_ROW_SPACING,
        vertical_alignment=ft.CrossAxisAlignment.START,
    )


def assistant_bubble(text: str, timestamp: datetime | None = None) -> ft.Row:
    theme = current_theme()
    meta_label = f"{CHATBOT_NAME} - {_time_label(timestamp)}" if timestamp else CHATBOT_NAME

    bubble = _bubble_container(
        text=text,
        bgcolor=theme.bot_bubble,
        text_color=theme.text_primary,
        border_color=ft.Colors.with_opacity(0.10, theme.accent),
        radius=_BOT_BUBBLE_RADIUS,
        padding=ft.Padding.symmetric(horizontal=16, vertical=12),
    )

    return ft.Row(
        controls=[
            _avatar(),
            ft.Container(
                expand=True,
                content=ft.Column(
                    controls=[
                        _meta_text(
                            meta_label,
                            color=theme.accent,
                            weight=ft.FontWeight.W_700,
                        ),
                        bubble,
                    ],
                    spacing=_META_SPACING,
                    tight=True,
                ),
            ),
        ],
        spacing=_ROW_SPACING,
        vertical_alignment=ft.CrossAxisAlignment.START,
    )


def typing_indicator() -> ft.Row:
    theme = current_theme()

    typing_bubble = ft.Container(
        expand=True,
        bgcolor=theme.bot_bubble,
        border_radius=_bubble_border_radius(*_TYPING_BUBBLE_RADIUS),
        border=ft.Border.all(
            1,
            ft.Colors.with_opacity(0.10, theme.accent),
        ),
        padding=ft.Padding.symmetric(horizontal=14, vertical=10),
        content=ft.Row(
            controls=[
                ft.Text(
                    f"{CHATBOT_NAME} is typing",
                    color=theme.text_muted,
                    size=12,
                    italic=True,
                ),
                ft.ProgressRing(
                    width=14,
                    height=14,
                    stroke_width=2,
                    color=theme.accent,
                ),
            ],
            spacing=8,
            tight=True,
        ),
    )

    return ft.Row(
        controls=[
            _avatar(),
            typing_bubble,
        ],
        spacing=_ROW_SPACING,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )

