from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any, cast
from flet.controls.control_event import Event

import flet as ft

from nemorax.frontend import api_client
from nemorax.frontend.config import APP_NAME, BRAND_NAME, ThemePalette, current_theme, set_show_splash
from nemorax.frontend.responsive import get_layout_config


_LOADING_STEPS: list[tuple[str, float]] = [
    ("Connecting...", 0.55),
    ("Loading history...", 0.45),
    ("Almost ready...", 0.35),
]
_MOBILE_WEB_BREAKPOINT = 800.0
_MOBILE_WEB_RESIZE_WIDTH_DELTA = 12.0


class SplashPage(ft.Container):
    def __init__(
        self,
        page: ft.Page,
        on_continue: Callable[[], None] | None = None,
    ) -> None:
        super().__init__()
        self._page = page
        self._on_continue = on_continue
        self._dont_show = False
        self._loading = False

        self._footer_ref = ft.Ref[ft.Container]()
        self._status_ref = ft.Ref[ft.Text]()
        self._bar_ref = ft.Ref[ft.Container]()
        self._last_viewport_width, self._last_viewport_height = self._page_size()

        self.padding = 0
        self.margin = 0

        self._refresh()
        self._page.on_resize = self._on_resize

    @staticmethod
    def _safe_update(control: ft.Control | None) -> None:
        if control is None:
            return

        try:
            if getattr(control, "page", None) is not None:
                control.update()
        except RuntimeError:
            pass

    def _page_size(self) -> tuple[float, float]:
        width = float(self._page.width or 1320)
        height = float(self._page.height or 860)
        return width, height

    def _on_resize(self, _: ft.PageResizeEvent) -> None:
        if self._loading:
            return

        width, height = self._page_size()
        width_delta = abs(width - self._last_viewport_width)
        if bool(getattr(self._page, "web", False)) and width < _MOBILE_WEB_BREAKPOINT:
            self._last_viewport_width = width
            self._last_viewport_height = height
            if width_delta < _MOBILE_WEB_RESIZE_WIDTH_DELTA:
                return

        self._last_viewport_width = width
        self._last_viewport_height = height

        self._refresh()
        self._safe_update(self)

    def _refresh(self) -> None:
        self.width, self.height = self._page_size()
        self.content = self._build()

    @staticmethod
    def _build_brand_block(
        *,
        title_size: int | float,
        subtitle_size: int | float,
    ) -> ft.Column:
        theme = current_theme()
        return ft.Column(
            controls=[
                ft.Text(
                    BRAND_NAME,
                    size=title_size,
                    weight=ft.FontWeight.W_900,
                    color=theme.text_primary,
                ),
                ft.Text(
                    APP_NAME,
                    size=subtitle_size,
                    weight=ft.FontWeight.W_700,
                    color=theme.accent,
                ),
            ],
            tight=True,
            spacing=6,
        )

    @staticmethod
    def _build_logo_chip(compact: bool) -> ft.Container:
        theme = current_theme()
        size = 52 if compact else 72
        radius = 14 if compact else 20
        text_size = 20 if compact else 30

        return ft.Container(
            width=size,
            height=size,
            border_radius=radius,
            bgcolor=ft.Colors.with_opacity(0.14, theme.text_primary),
            border=ft.Border.all(1, ft.Colors.with_opacity(0.22, theme.text_primary)),
            alignment=ft.Alignment(0, 0),
            content=ft.Text(
                "N",
                size=text_size,
                weight=ft.FontWeight.W_800,
                color=theme.text_primary,
            ),
        )

    def _build_checkbox_row(self, compact: bool) -> ft.Row:
        theme = current_theme()
        return ft.Row(
            controls=[
                ft.Checkbox(
                    value=False,
                    on_change=self._handle_checkbox,
                    fill_color={
                        ft.ControlState.SELECTED: theme.accent,
                        ft.ControlState.DEFAULT: ft.Colors.TRANSPARENT,
                    },
                    check_color=theme.sidebar_bg,
                    border_side=ft.BorderSide(
                        width=1.2,
                        color=ft.Colors.with_opacity(0.70, theme.text_primary),
                    ),
                ),
                ft.Text(
                    "DON'T SHOW THIS AGAIN",
                    size=10 if compact else 11,
                    weight=ft.FontWeight.W_700,
                    color=ft.Colors.with_opacity(0.92, theme.text_primary),
                ),
            ],
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def _build(self) -> ft.Control:
        theme = current_theme()
        cfg = get_layout_config(self._page)

        card_width = cfg["splash_card_width"]
        title_size = cfg["font_size_splash_title"]
        subtitle_size = cfg["font_size_splash_sub"]
        body_size = cfg["font_size_splash_body"]
        pad_h = cfg["splash_padding_h"]
        pad_v = cfg["splash_padding_v"]
        orb_top = cfg["orb_size_top"]
        orb_bottom = cfg["orb_size_bottom"]
        top_padding = cfg["top_padding"]
        compact = cfg["compact"]

        self.bgcolor = theme.grad_bottom
        self.gradient = None

        gradient_bg = ft.Container(
            expand=True,
            gradient=ft.LinearGradient(
                begin=ft.Alignment(-1, -1),
                end=ft.Alignment(1, 1),
                colors=[theme.grad_top, theme.grad_mid, theme.grad_bottom],
            ),
        )

        top_orb = ft.Container(
            width=orb_top,
            height=orb_top,
            border_radius=999,
            bgcolor=ft.Colors.with_opacity(0.14, theme.accent),
        )
        bottom_orb = ft.Container(
            width=orb_bottom,
            height=orb_bottom,
            border_radius=999,
            bgcolor=ft.Colors.with_opacity(0.10, theme.text_primary),
        )

        header = ft.Row(
            controls=[
                self._build_brand_block(
                    title_size=title_size,
                    subtitle_size=subtitle_size,
                ),
                self._build_logo_chip(compact),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.START,
        )

        description = ft.Text(
            "Nemorax is the AI platform developed to support students, teachers, and "
            "the wider campus community of North Eastern Mindanao State University.\n\n"
            "It is designed to answer queries, provide reliable information, and support "
            "academic and school-related needs. By streamlining access to knowledge and "
            "improving communication, Nemorax improves productivity and the overall campus experience.",
            size=body_size,
            color=ft.Colors.with_opacity(0.94, theme.text_primary),
            weight=ft.FontWeight.W_500,
        )

        description_secondary = ft.Text(
            "Nemis is the first assistant built on Nemorax, focused on handling "
            "academic inquiries, campus-related concerns, and general questions.\n\n"
            "As the first assistant experience from Nemorax, Nemis is the starting point for a "
            "scalable system that can expand into more advanced and specialized AI solutions over time.",
            size=max(10, body_size - 1),
            color=ft.Colors.with_opacity(0.84, theme.text_secondary),
        )

        footer_content = (
            self._build_loading_footer(theme, cfg)
            if self._loading
            else self._build_cta_footer(theme, cfg, self._build_checkbox_row(compact))
        )

        footer_container = ft.Container(
            ref=self._footer_ref,
            content=footer_content,
        )

        card_children: list[ft.Control] = [
            header,
            ft.Container(height=14 if compact else 18),
            description,
        ]

        if not (cfg["is_mobile"] and compact):
            card_children.extend(
                [
                    ft.Container(height=10 if compact else 12),
                    description_secondary,
                ]
            )

        card_children.extend(
            [
                ft.Container(height=14 if compact else 18),
                footer_container,
            ]
        )

        card_top_margin = top_padding if cfg["is_ios"] else 0

        splash_card = ft.Container(
            width=card_width,
            margin=ft.Margin.only(top=card_top_margin),
            padding=ft.Padding.symmetric(horizontal=pad_h, vertical=pad_v),
            border_radius=50 if not compact else 36,
            bgcolor=ft.Colors.with_opacity(0.22, theme.sidebar_bg),
            border=ft.Border.all(1, ft.Colors.with_opacity(0.18, theme.border)),
            shadow=ft.BoxShadow(
                spread_radius=0,
                blur_radius=20,
                color=ft.Colors.with_opacity(0.22, theme.shadow),
                offset=ft.Offset(0, 12),
            ),
            content=ft.Column(
                controls=card_children,
                tight=True,
                spacing=0,
                scroll=ft.ScrollMode.AUTO if cfg["is_mobile"] else ft.ScrollMode.HIDDEN,
            ),
        )

        return ft.Stack(
            expand=True,
            controls=[
                gradient_bg,
                ft.Container(
                    expand=True,
                    content=ft.Row(
                        controls=[
                            ft.Container(expand=True),
                            ft.Container(
                                margin=ft.Margin.only(top=22, right=24),
                                content=top_orb,
                            ),
                        ],
                        expand=True,
                        vertical_alignment=ft.CrossAxisAlignment.START,
                    ),
                ),
                ft.Container(
                    expand=True,
                    content=ft.Column(
                        controls=[
                            ft.Container(expand=True),
                            ft.Container(
                                margin=ft.Margin.only(left=-70, bottom=-50),
                                content=bottom_orb,
                            ),
                        ],
                        expand=True,
                        spacing=0,
                    ),
                ),
                ft.Container(
                    expand=True,
                    alignment=ft.Alignment(0, 0),
                    content=splash_card,
                ),
            ],
        )

    def _build_cta_footer(
        self,
        theme: ThemePalette,
        cfg: dict[str, object],
        checkbox_row: ft.Control,
    ) -> ft.Control:
        compact = cfg["compact"]

        cta_button = ft.Button(
            content=ft.Text(
                "TALK TO NEMIS",
                size=11 if compact else 12,
                weight=ft.FontWeight.W_800,
                color=theme.sidebar_bg,
            ),
            on_click=self._handle_continue,
            style=cast(Any, ft.ButtonStyle)(
                bgcolor=theme.accent,
                padding=ft.Padding.symmetric(
                    horizontal=14 if compact else 18,
                    vertical=14 if compact else 16,
                ),
                shape=ft.RoundedRectangleBorder(radius=8),
                elevation=0,
            ),
        )

        return ft.Row(
            controls=[checkbox_row, cta_button],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def _build_loading_footer(self, theme: ThemePalette, cfg: dict[str, object]) -> ft.Control:
        compact = cfg["compact"]
        bar_height = 3 if compact else 4

        status_text = ft.Text(
            ref=self._status_ref,
            value=_LOADING_STEPS[0][0],
            size=11 if compact else 12,
            weight=ft.FontWeight.W_700,
            color=ft.Colors.with_opacity(0.85, theme.accent),
            italic=True,
        )

        glow_dot = ft.Container(
            width=10 if compact else 11,
            height=10 if compact else 11,
            border_radius=999,
            bgcolor=theme.accent,
            shadow=ft.BoxShadow(
                blur_radius=12,
                spread_radius=2,
                color=ft.Colors.with_opacity(0.60, theme.accent),
                offset=ft.Offset(0, 0),
            ),
        )

        top_row = ft.Row(
            controls=[glow_dot, status_text],
            spacing=10,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        bar_fill = ft.Container(
            ref=self._bar_ref,
            width=0,
            height=bar_height,
            border_radius=bar_height,
            bgcolor=theme.accent,
            shadow=ft.BoxShadow(
                blur_radius=8,
                color=ft.Colors.with_opacity(0.55, theme.accent),
                offset=ft.Offset(0, 0),
            ),
            animate_size=ft.Animation(420, ft.AnimationCurve.EASE_OUT),
        )

        bar_track = ft.Container(
            expand=True,
            height=bar_height,
            border_radius=bar_height,
            bgcolor=ft.Colors.with_opacity(0.18, theme.border),
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
            content=ft.Stack(
                expand=True,
                controls=[bar_fill],
            ),
        )

        return ft.Column(
            controls=[
                top_row,
                ft.Container(height=10),
                bar_track,
            ],
            spacing=0,
            tight=True,
        )

    def _handle_checkbox(self, event: Event[ft.Checkbox]) -> None:
        self._dont_show = bool(event.control.value)

    def _swap_footer_to_loading(self) -> None:
        theme = current_theme()
        cfg = get_layout_config(self._page)

        if self._footer_ref.current is None:
            return

        self._footer_ref.current.content = self._build_loading_footer(theme, cfg)
        self._safe_update(self._footer_ref.current)

    def _handle_continue(self, _: Event[ft.Button] | None = None) -> None:
        if self._loading:
            return

        self._loading = True
        set_show_splash(not self._dont_show)
        self._swap_footer_to_loading()
        self._page.run_task(self._run_loading_sequence)

    async def _run_loading_sequence(self) -> None:
        total_steps = len(_LOADING_STEPS)
        bar_max_width = self._bar_max_width()

        await self._set_step(0, bar_max_width, total_steps)
        try:
            loop = asyncio.get_running_loop()
            await asyncio.wait_for(
                loop.run_in_executor(None, api_client.check_health),
                timeout=6.0,
            )
        except (asyncio.TimeoutError, RuntimeError, OSError):
            pass

        await self._set_step(1, bar_max_width, total_steps)
        await asyncio.sleep(_LOADING_STEPS[1][1])

        await self._set_step(2, bar_max_width, total_steps)
        await asyncio.sleep(_LOADING_STEPS[2][1])

        await self._animate_bar(bar_max_width)
        await asyncio.sleep(0.20)

        if self._on_continue is not None:
            self._on_continue()

    async def _set_step(
        self,
        index: int,
        bar_max_width: float,
        total_steps: int,
    ) -> None:
        label, minimum_seconds = _LOADING_STEPS[index]
        fraction = (index + 0.6) / total_steps
        target_width = bar_max_width * fraction

        if self._status_ref.current is not None:
            self._status_ref.current.value = label
            self._safe_update(self._status_ref.current)

        await self._animate_bar(target_width)
        await asyncio.sleep(minimum_seconds)

    async def _animate_bar(self, target_width: float) -> None:
        if self._bar_ref.current is not None:
            self._bar_ref.current.width = max(0.0, target_width)
            self._safe_update(self._bar_ref.current)

        await asyncio.sleep(0.02)

    def _bar_max_width(self) -> float:
        cfg = get_layout_config(self._page)
        return max(80.0, cfg["splash_card_width"] - (cfg["splash_padding_h"] * 2))
