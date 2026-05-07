from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any

import flet as ft

if not hasattr(ft, "colors"):
    ft.colors = ft.Colors  # type: ignore[attr-defined]

THEME: dict[str, str] = {
    "grad_top": "#4FC3F7",
    "grad_mid": "#5C6BC0",
    "grad_bottom": "#7B1FA2",
    "blob": "#FFFFFF",
    "card_bg": "#1E2A4A",
    "avatar_bg": "#2E3D6B",
    "logo_start": "#4FC3F7",
    "logo_end": "#7B1FA2",
    "text_primary": "#FFFFFF",
    "text_secondary": "#90CAF9",
    "progress": "#4FC3F7",
    "progress_track": "#FFFFFF",
    "button_text": "#FFFFFF",
    "shadow": "#111827",
}

BACKEND_PRIMARY = os.getenv("NEMIS_PRIMARY_BACKEND_URL", "https://nemis-backend.onrender.com").rstrip("/")
BACKEND_SECONDARY = os.getenv("NEMIS_SECONDARY_BACKEND_URL", "https://nemis-backend.up.railway.app").rstrip("/")


class LoadingScreenError(Exception):
    """Raised when the loading screen cannot complete its startup flow."""


class BackendEndpointMissingError(LoadingScreenError):
    """Raised when no backend endpoint is configured for the loading screen."""


@dataclass(frozen=True)
class PlatformConfig:
    is_web: bool
    is_mobile: bool
    card_width: float
    card_padding_h: int
    card_padding_v: int
    font_scale: float
    show_blobs: bool


STATUS_MESSAGES = [
    "Restoring your session...",
    "Loading your profile...",
    "Almost there...",
]


def get_backend_urls() -> tuple[str, str]:
    if not BACKEND_PRIMARY and not BACKEND_SECONDARY:
        raise BackendEndpointMissingError("No Nemis backend endpoint is configured.")
    return BACKEND_PRIMARY, BACKEND_SECONDARY


def get_platform_name(page: ft.Page) -> str:
    platform_name = str(getattr(page, "platform", "") or "").lower()
    if platform_name.startswith("pageplatform."):
        platform_name = platform_name.rsplit(".", 1)[-1]
    return platform_name


def is_mobile_web(page: ft.Page) -> bool:
    viewport_width = float(page.width or 390)
    return bool(getattr(page, "web", False)) and viewport_width < 760


def build_platform_config(page: ft.Page) -> PlatformConfig:
    platform_name = get_platform_name(page)
    is_web = bool(getattr(page, "web", False))
    is_native_mobile = platform_name in {"android", "ios"}
    is_mobile = is_native_mobile or is_mobile_web(page)
    viewport_width = float(page.width or (390 if is_mobile else 1200))

    if is_mobile:
        card_width = min(max(280, viewport_width * 0.88), 400)
        return PlatformConfig(
            is_web=is_web,
            is_mobile=True,
            card_width=card_width,
            card_padding_h=22,
            card_padding_v=26,
            font_scale=0.88,
            show_blobs=False,
        )

    return PlatformConfig(
        is_web=is_web,
        is_mobile=False,
        card_width=520,
        card_padding_h=34,
        card_padding_v=34,
        font_scale=1.0,
        show_blobs=True,
    )


def scale_size(value: int | float, scale: float) -> float:
    return round(float(value) * scale, 1)


def build_gradient_background(page: ft.Page) -> ft.Container:
    return ft.Container(
        expand=True,
        width=page.width,
        height=page.height,
        gradient=ft.LinearGradient(
            begin=ft.alignment.top_left,
            end=ft.alignment.bottom_right,
            colors=[THEME["grad_top"], THEME["grad_mid"], THEME["grad_bottom"]],
        ),
    )


def build_avatar_button(font_scale: float) -> ft.Container:
    return ft.Container(
        width=48,
        height=48,
        border_radius=12,
        bgcolor=THEME["avatar_bg"],
        alignment=ft.Alignment(0, 0),
        content=ft.Text(
            "N",
            size=scale_size(22, font_scale),
            weight=ft.FontWeight.W_800,
            color=THEME["text_primary"],
        ),
    )


def build_robot_logo(font_scale: float) -> ft.Container:
    return ft.Container(
        width=72,
        height=72,
        border_radius=22,
        alignment=ft.Alignment(0, 0),
        gradient=ft.LinearGradient(
            begin=ft.Alignment(-1, -1),
            end=ft.Alignment(1, 1),
            colors=[THEME["logo_start"], THEME["logo_end"]],
        ),
        shadow=ft.BoxShadow(
            blur_radius=18,
            spread_radius=0,
            color=ft.Colors.with_opacity(0.28, THEME["grad_bottom"]),
            offset=ft.Offset(0, 8),
        ),
        content=ft.Text(
            "N",
            size=scale_size(34, font_scale),
            weight=ft.FontWeight.W_900,
            color=THEME["text_primary"],
        ),
    )


def build_loading_card(
    page: ft.Page,
    platform_config: PlatformConfig,
    status_ref: ft.Ref[ft.Text],
    progress_ref: ft.Ref[ft.ProgressBar],
) -> ft.Container:
    font_scale = platform_config.font_scale
    title_block = ft.Column(
        spacing=2,
        tight=True,
        controls=[
            ft.Text(
                "Nemis",
                size=scale_size(28, font_scale),
                weight=ft.FontWeight.W_800,
                color=THEME["text_primary"],
            ),
            ft.Text(
                "Campus assistant",
                size=scale_size(14, font_scale),
                color=THEME["text_secondary"],
            ),
        ],
    )
    hidden_talk_button_label = ft.Container(
        alignment=ft.Alignment(1, 0),
        visible=False,
        content=ft.Text(
            "TALK TO NEMIS",
            size=scale_size(12, font_scale),
            weight=ft.FontWeight.W_800,
            color=THEME["button_text"],
        ),
    )

    return ft.Container(
        width=platform_config.card_width,
        expand=False,
        padding=ft.Padding.symmetric(horizontal=platform_config.card_padding_h, vertical=platform_config.card_padding_v),
        border_radius=24,
        bgcolor=ft.Colors.with_opacity(0.85, THEME["card_bg"]),
        border=ft.Border.all(1, ft.Colors.with_opacity(0.18, THEME["blob"])),
        shadow=ft.BoxShadow(
            blur_radius=34,
            spread_radius=0,
            color=ft.Colors.with_opacity(0.28, THEME["shadow"]),
            offset=ft.Offset(0, 18),
        ),
        content=ft.Column(
            tight=True,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=0,
            controls=[
                ft.Row(
                    controls=[
                        title_block,
                        ft.Container(expand=True),
                        build_avatar_button(font_scale),
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.START,
                ),
                ft.Container(height=34 if platform_config.is_mobile else 42),
                build_robot_logo(font_scale),
                ft.Container(height=28 if platform_config.is_mobile else 34),
                ft.Text(
                    ref=status_ref,
                    value=STATUS_MESSAGES[0],
                    size=scale_size(16, font_scale),
                    italic=True,
                    text_align=ft.TextAlign.CENTER,
                    color=THEME["text_primary"],
                ),
                ft.Container(height=18),
                ft.ProgressBar(
                    ref=progress_ref,
                    value=0,
                    height=5,
                    color=THEME["progress"],
                    bgcolor=ft.Colors.with_opacity(0.15, THEME["progress_track"]),
                    border_radius=8,
                ),
                ft.Container(height=18),
                hidden_talk_button_label,
            ],
        ),
    )


def build_loading_screen(
    page: ft.Page,
    status_ref: ft.Ref[ft.Text],
    progress_ref: ft.Ref[ft.ProgressBar],
) -> ft.Stack:
    platform_config = build_platform_config(page)
    session_card = build_loading_card(page, platform_config, status_ref, progress_ref)
    gradient_background = build_gradient_background(page)
    centered_session_card = ft.Container(
        expand=True,
        width=page.width,
        height=page.height,
        alignment=ft.alignment.center,
        bgcolor=ft.colors.TRANSPARENT,
        content=session_card,
    )

    return ft.Stack(
        expand=True,
        width=page.width,
        height=page.height,
        controls=[gradient_background, centered_session_card],
    )


async def animate_status(page: ft.Page, status_ref: ft.Ref[ft.Text]) -> None:
    message_index = 0
    while True:
        await asyncio.sleep(1.2)
        if status_ref.current is None:
            return
        message_index += 1
        if message_index >= len(STATUS_MESSAGES):
            return
        status_ref.current.value = STATUS_MESSAGES[message_index]
        page.update()


async def animate_progress(page: ft.Page, progress_ref: ft.Ref[ft.ProgressBar], status_ref: ft.Ref[ft.Text]) -> None:
    total_steps = 60
    for current_step in range(total_steps + 1):
        if progress_ref.current is None:
            return
        progress_ref.current.value = current_step / total_steps
        page.update()
        await asyncio.sleep(3 / total_steps)

    if status_ref.current is not None:
        status_ref.current.value = "Session ready."
        page.update()


async def main(page: ft.Page) -> None:
    print(f"[Nemis] Platform: {page.platform}, Web: {page.web}")
    page.title = "Nemis"
    page.padding = 0
    page.margin = 0
    page.spacing = 0
    page.bgcolor = ft.colors.TRANSPARENT
    try:
        page.window_bgcolor = ft.colors.TRANSPARENT
    except Exception:
        pass
    page.scroll = None
    page.theme_mode = ft.ThemeMode.DARK
    page.horizontal_alignment = ft.CrossAxisAlignment.STRETCH
    page.vertical_alignment = ft.MainAxisAlignment.START
    get_backend_urls()

    status_ref = ft.Ref[ft.Text]()
    progress_ref = ft.Ref[ft.ProgressBar]()
    root_stack = build_loading_screen(page, status_ref, progress_ref)

    def on_resize(event: Any) -> None:
        root_stack.width = page.width
        root_stack.height = page.height
        root_stack.controls[0].width = page.width
        root_stack.controls[0].height = page.height
        root_stack.controls[1].width = page.width
        root_stack.controls[1].height = page.height
        page.update()

    page.on_resize = on_resize
    page.controls.clear()
    page.add(root_stack)
    page.update()

    await asyncio.gather(
        animate_status(page, status_ref),
        animate_progress(page, progress_ref, status_ref),
    )


ft.app(target=main)
