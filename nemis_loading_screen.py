from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import flet as ft


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
}

STATUS_MESSAGES = [
    "Restoring your session...",
    "Loading your profile...",
    "Almost there...",
]


@dataclass(frozen=True)
class PlatformConfig:
    is_web: bool
    is_mobile: bool
    card_width: float
    card_padding_h: int
    card_padding_v: int
    font_scale: float
    show_blobs: bool


def _platform_name(page: ft.Page) -> str:
    platform = str(getattr(page, "platform", "") or "").lower()
    if platform.startswith("pageplatform."):
        platform = platform.rsplit(".", 1)[-1]
    return platform


def _is_mobile_web(page: ft.Page) -> bool:
    width = float(page.width or 390)
    return bool(getattr(page, "web", False)) and width < 760


def _platform_config(page: ft.Page) -> PlatformConfig:
    platform = _platform_name(page)
    is_web = bool(getattr(page, "web", False))
    is_native_mobile = platform in {"android", "ios"}
    is_mobile = is_native_mobile or _is_mobile_web(page)
    page_width = float(page.width or (390 if is_mobile else 1200))

    # Mobile native and mobile web use almost-full-width cards so the layout
    # stays centered and never becomes a narrow side panel.
    if is_mobile:
        # FIXED
        card_width = min(max(280, page_width * 0.88), 400)
        return PlatformConfig(
            is_web=is_web,
            is_mobile=True,
            card_width=card_width,
            card_padding_h=22,
            card_padding_v=26,
            font_scale=0.88,
            show_blobs=False,
        )

    # Desktop native and desktop web keep the wider fixed card and decorative
    # blobs because there is enough canvas area for the frosted-glass treatment.
    return PlatformConfig(
        is_web=is_web,
        is_mobile=False,
        # FIXED
        card_width=520,
        card_padding_h=34,
        card_padding_v=34,
        font_scale=1.0,
        show_blobs=True,
    )


def _scaled(value: int | float, scale: float) -> float:
    return round(float(value) * scale, 1)


def _gradient_background() -> ft.Container:
    return ft.Container(
        expand=True,
        gradient=ft.LinearGradient(
            begin=ft.Alignment(-1, -1),
            end=ft.Alignment(1, 1),
            colors=[THEME["grad_top"], THEME["grad_mid"], THEME["grad_bottom"]],
        ),
    )


def _blob(*, top: int | None = None, right: int | None = None, bottom: int | None = None, left: int | None = None) -> ft.Container:
    return ft.Container(
        top=top,
        right=right,
        bottom=bottom,
        left=left,
        width=300,
        height=300,
        border_radius=150,
        bgcolor=ft.Colors.with_opacity(0.08, THEME["blob"]),
    )


def _avatar_button(font_scale: float) -> ft.Container:
    return ft.Container(
        width=48,
        height=48,
        border_radius=12,
        bgcolor=THEME["avatar_bg"],
        alignment=ft.Alignment(0, 0),
        content=ft.Text(
            "N",
            size=_scaled(22, font_scale),
            weight=ft.FontWeight.W_800,
            color=THEME["text_primary"],
        ),
    )


def _robot_logo(font_scale: float) -> ft.Container:
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
            size=_scaled(34, font_scale),
            weight=ft.FontWeight.W_900,
            color=THEME["text_primary"],
        ),
    )


def _loading_card(
    page: ft.Page,
    cfg: PlatformConfig,
    status_ref: ft.Ref[ft.Text],
    progress_ref: ft.Ref[ft.ProgressBar],
) -> ft.Container:
    font_scale = cfg.font_scale

    title_block = ft.Column(
        spacing=2,
        tight=True,
        controls=[
            ft.Text(
                "Nemis",
                size=_scaled(28, font_scale),
                weight=ft.FontWeight.W_800,
                color=THEME["text_primary"],
            ),
            ft.Text(
                "Campus assistant",
                size=_scaled(14, font_scale),
                color=THEME["text_secondary"],
            ),
        ],
    )

    hidden_cta = ft.Container(
        alignment=ft.Alignment(1, 0),
        visible=False,
        content=ft.Text(
            "TALK TO NEMIS",
            size=_scaled(12, font_scale),
            weight=ft.FontWeight.W_800,
            color=THEME["button_text"],
        ),
    )

    return ft.Container(
        width=cfg.card_width,
        padding=ft.Padding.symmetric(horizontal=cfg.card_padding_h, vertical=cfg.card_padding_v),
        border_radius=24,
        bgcolor=ft.Colors.with_opacity(0.85, THEME["card_bg"]),
        border=ft.Border.all(1, ft.Colors.with_opacity(0.18, THEME["blob"])),
        shadow=ft.BoxShadow(
            blur_radius=34,
            spread_radius=0,
            color=ft.Colors.with_opacity(0.28, "#111827"),
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
                        _avatar_button(font_scale),
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.START,
                ),
                ft.Container(height=34 if cfg.is_mobile else 42),
                _robot_logo(font_scale),
                ft.Container(height=28 if cfg.is_mobile else 34),
                ft.Text(
                    ref=status_ref,
                    value=STATUS_MESSAGES[0],
                    size=_scaled(16, font_scale),
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
                hidden_cta,
            ],
        ),
    )


def build_loading_screen(
    page: ft.Page,
    status_ref: ft.Ref[ft.Text],
    progress_ref: ft.Ref[ft.ProgressBar],
) -> ft.Control:
    cfg = _platform_config(page)

    stack_controls: list[ft.Control] = [_gradient_background()]

    # Android/iOS/mobile web skip decorative blobs because they clip poorly on
    # small screens and can make the centered card feel crowded.
    if cfg.show_blobs:
        stack_controls.extend(
            [
                _blob(top=-70, right=-70),
                _blob(bottom=-90, left=-85),
            ]
        )

    # The card is last in the Stack because Flet renders children back-to-front
    # on native mobile targets.
    stack_controls.append(
        ft.Container(
            expand=True,
            alignment=ft.Alignment(0, 0),
            padding=ft.Padding.symmetric(horizontal=16 if cfg.is_mobile else 24),
            content=_loading_card(page, cfg, status_ref, progress_ref),
        )
    )

    return ft.Stack(expand=True, controls=stack_controls)


async def animate_status(page: ft.Page, status_ref: ft.Ref[ft.Text]) -> None:
    index = 0
    while True:
        await asyncio.sleep(1.2)
        if status_ref.current is None:
            return
        index += 1
        if index >= len(STATUS_MESSAGES):
            return
        status_ref.current.value = STATUS_MESSAGES[index]
        page.update()


async def animate_progress(page: ft.Page, progress_ref: ft.Ref[ft.ProgressBar], status_ref: ft.Ref[ft.Text]) -> None:
    steps = 60
    for step in range(steps + 1):
        if progress_ref.current is None:
            return
        progress_ref.current.value = step / steps
        page.update()
        await asyncio.sleep(3 / steps)

    if status_ref.current is not None:
        status_ref.current.value = "Session ready."
        page.update()


async def main(page: ft.Page) -> None:
    print(f"[Nemis] Platform: {page.platform}, Web: {page.web}")

    page.title = "Nemis"
    # FIXED
    page.bgcolor = "#7B1FA2"
    page.padding = 0
    # FIXED
    if hasattr(page, "margin"):
        # FIXED
        page.margin = 0
    page.spacing = 0
    page.scroll = ft.ScrollMode.HIDDEN
    page.theme_mode = ft.ThemeMode.DARK
    page.horizontal_alignment = ft.CrossAxisAlignment.STRETCH
    page.vertical_alignment = ft.MainAxisAlignment.START

    status_ref = ft.Ref[ft.Text]()
    progress_ref = ft.Ref[ft.ProgressBar]()

    page.add(build_loading_screen(page, status_ref, progress_ref))
    page.update()

    await asyncio.gather(
        animate_status(page, status_ref),
        animate_progress(page, progress_ref, status_ref),
    )


if __name__ == "__main__":
    ft.app(target=main)
    # ft.app(target=main, view=ft.AppView.WEB_BROWSER)
