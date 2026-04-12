"""
frontend/responsive.py
----------------------
Platform-aware layout configuration for Nemorax.
"""
from __future__ import annotations

from typing import Any

import flet as ft


_DESKTOP_PLATFORMS = {
    ft.PagePlatform.WINDOWS,
    ft.PagePlatform.LINUX,
    ft.PagePlatform.MACOS,
}
_MOBILE_WEB_MAX_WIDTH = 800


LayoutConfig = dict[str, Any]


def _positive_float(value: object, fallback: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback

    return number if number > 0 else fallback


def _page_size(page: ft.Page) -> tuple[float, float]:
    width = _positive_float(page.width or getattr(page, "window_width", None), 1320.0)
    height = _positive_float(page.height or getattr(page, "window_height", None), 860.0)
    return max(width, 320.0), max(height, 568.0)


def _ios_safe_top(height: float) -> int:
    """Conservative notch / Dynamic Island spacing heuristic."""
    if height < 700:
        return 28
    if height < 800:
        return 50
    if height < 871:
        return 58
    return 64


def _android_safe_top(height: float) -> int:
    """Conservative status bar / camera cutout spacing heuristic."""
    if height < 700:
        return 26
    if height < 840:
        return 30
    return 34


def _base_config(
    *,
    width: float,
    height: float,
    is_mobile: bool,
    is_ios: bool,
    is_android: bool,
    compact: bool,
    sidebar_visible: bool,
    top_padding: int,
    font_size_title: int | float,
    font_size_subtitle: int | float,
    font_size_body: int | float,
    font_size_small: int | float,
    font_size_hero_title: int | float,
    font_size_splash_title: int | float,
    font_size_splash_sub: int | float,
    font_size_splash_body: int | float,
    padding_horizontal: int,
    padding_vertical: int,
    padding_card_h: int,
    padding_card_v: int,
    button_height: int,
    logo_size_header: int,
    logo_size_hero: int,
    avatar_size: int,
    input_font_size: int,
    chip_font_size: int,
    gap_header_body: int,
    gap_body_composer: int,
    drawer_width: float,
    splash_card_width: float,
    splash_padding_h: int,
    splash_padding_v: int,
    orb_size_top: int,
    orb_size_bottom: int,
) -> LayoutConfig:
    return {
        "top_padding": top_padding,
        "font_size_title": font_size_title,
        "font_size_subtitle": font_size_subtitle,
        "font_size_body": font_size_body,
        "font_size_small": font_size_small,
        "font_size_hero_title": font_size_hero_title,
        "font_size_splash_title": font_size_splash_title,
        "font_size_splash_sub": font_size_splash_sub,
        "font_size_splash_body": font_size_splash_body,
        "padding_horizontal": padding_horizontal,
        "padding_vertical": padding_vertical,
        "padding_card_h": padding_card_h,
        "padding_card_v": padding_card_v,
        "button_height": button_height,
        "sidebar_visible": sidebar_visible,
        "logo_size_header": logo_size_header,
        "logo_size_hero": logo_size_hero,
        "avatar_size": avatar_size,
        "input_font_size": input_font_size,
        "chip_font_size": chip_font_size,
        "gap_header_body": gap_header_body,
        "gap_body_composer": gap_body_composer,
        "compact": compact,
        "is_mobile": is_mobile,
        "is_ios": is_ios,
        "is_android": is_android,
        "screen_width": width,
        "screen_height": height,
        "drawer_width": drawer_width,
        "splash_card_width": splash_card_width,
        "splash_padding_h": splash_padding_h,
        "splash_padding_v": splash_padding_v,
        "orb_size_top": orb_size_top,
        "orb_size_bottom": orb_size_bottom,
    }


def is_desktop(page: ft.Page) -> bool:
    platform = getattr(page, "platform", None)
    return platform in _DESKTOP_PLATFORMS


def is_web(page: ft.Page) -> bool:
    return bool(getattr(page, "web", False))


def is_android(page: ft.Page) -> bool:
    return getattr(page, "platform", None) == ft.PagePlatform.ANDROID


def is_ios(page: ft.Page) -> bool:
    return getattr(page, "platform", None) == ft.PagePlatform.IOS


def is_mobile(page: ft.Page) -> bool:
    return is_android(page) or is_ios(page)


def is_desktop_or_web(page: ft.Page) -> bool:
    return is_desktop(page) or is_web(page)


def _is_mobile_web(page: ft.Page, width: float) -> bool:
    return is_web(page) and width < _MOBILE_WEB_MAX_WIDTH


def get_layout_config(page: ft.Page) -> LayoutConfig:
    """
    Return a platform-aware layout config dict used throughout the UI.
    """
    width, height = _page_size(page)
    platform = getattr(page, "platform", None)

    if _is_mobile_web(page, width):
        if platform == ft.PagePlatform.IOS:
            return _ios_config(width, height)
        if platform == ft.PagePlatform.ANDROID:
            return _android_config(width, height)
        return _mobile_web_config(width, height)

    if is_desktop_or_web(page):
        return _desktop_config(width, height)

    if platform == ft.PagePlatform.ANDROID:
        return _android_config(width, height)

    if platform == ft.PagePlatform.IOS:
        return _ios_config(width, height)

    return _desktop_config(width, height)


def _desktop_config(width: float, height: float) -> LayoutConfig:
    compact = width < 760

    return _base_config(
        width=width,
        height=height,
        is_mobile=False,
        is_ios=False,
        is_android=False,
        compact=compact,
        sidebar_visible=True,
        top_padding=0,
        font_size_title=28,
        font_size_subtitle=12,
        font_size_body=14,
        font_size_small=11,
        font_size_hero_title=34,
        font_size_splash_title=_splash_title_size(width),
        font_size_splash_sub=18 if width >= 760 else 14,
        font_size_splash_body=_splash_body_size(width),
        padding_horizontal=24,
        padding_vertical=24,
        padding_card_h=24,
        padding_card_v=20,
        button_height=44,
        logo_size_header=44,
        logo_size_hero=74,
        avatar_size=34,
        input_font_size=14,
        chip_font_size=12,
        gap_header_body=18,
        gap_body_composer=18,
        drawer_width=min(width * 0.84, 320),
        splash_card_width=_splash_card_width(width),
        splash_padding_h=36 if width >= 760 else 22,
        splash_padding_v=28 if width >= 760 else 18,
        orb_size_top=420 if width >= 760 else 240,
        orb_size_bottom=320 if width >= 760 else 180,
    )


def _android_config(width: float, height: float) -> LayoutConfig:
    compact = width < 380
    top_padding = _android_safe_top(height)

    if compact:
        font_size_title = 15
        font_size_subtitle = 9
        font_size_body = 12
        font_size_small = 10
        font_size_hero_title = 20
        padding_horizontal = 6
        padding_vertical = 6
        padding_card_h = 10
        padding_card_v = 8
        chip_font_size = 10
        input_font_size = 12
        gap_header_body = 6
        gap_body_composer = 6
        logo_size_header = 32
        logo_size_hero = 44
        avatar_size = 30
        font_size_splash_title = 22
        font_size_splash_sub = 12
        font_size_splash_body = 11
    else:
        font_size_title = 17
        font_size_subtitle = 9
        font_size_body = 13
        font_size_small = 10
        font_size_hero_title = 22
        padding_horizontal = 8
        padding_vertical = 8
        padding_card_h = 12
        padding_card_v = 10
        chip_font_size = 11
        input_font_size = 13
        gap_header_body = 8
        gap_body_composer = 8
        logo_size_header = 36
        logo_size_hero = 50
        avatar_size = 32
        font_size_splash_title = 28
        font_size_splash_sub = 14
        font_size_splash_body = 12

    return _base_config(
        width=width,
        height=height,
        is_mobile=True,
        is_ios=False,
        is_android=True,
        compact=compact,
        sidebar_visible=False,
        top_padding=top_padding,
        font_size_title=font_size_title,
        font_size_subtitle=font_size_subtitle,
        font_size_body=font_size_body,
        font_size_small=font_size_small,
        font_size_hero_title=font_size_hero_title,
        font_size_splash_title=font_size_splash_title,
        font_size_splash_sub=font_size_splash_sub,
        font_size_splash_body=font_size_splash_body,
        padding_horizontal=padding_horizontal,
        padding_vertical=padding_vertical,
        padding_card_h=padding_card_h,
        padding_card_v=padding_card_v,
        button_height=48,
        logo_size_header=logo_size_header,
        logo_size_hero=logo_size_hero,
        avatar_size=avatar_size,
        input_font_size=input_font_size,
        chip_font_size=chip_font_size,
        gap_header_body=gap_header_body,
        gap_body_composer=gap_body_composer,
        drawer_width=min(width * 0.84, 320),
        splash_card_width=width * 0.92,
        splash_padding_h=18 if not compact else 14,
        splash_padding_v=18 if not compact else 14,
        orb_size_top=200 if compact else 240,
        orb_size_bottom=150 if compact else 180,
    )


def _ios_config(width: float, height: float) -> LayoutConfig:
    compact = width < 380

    if height < 700:
        size_category = "se"
        top_padding = 20
        font_size_title = 15
        font_size_subtitle = 9
        font_size_body = 12
        font_size_small = 10
        font_size_hero_title = 20
        padding_horizontal = 6
        padding_vertical = 6
        padding_card_h = 10
        padding_card_v = 8
        chip_font_size = 10
        input_font_size = 12
        gap_header_body = 6
        gap_body_composer = 6
        logo_size_header = 32
        logo_size_hero = 44
        avatar_size = 30
    elif height < 870:
        size_category = "standard"
        top_padding = 44
        font_size_title = 16
        font_size_subtitle = 9
        font_size_body = 12
        font_size_small = 10
        font_size_hero_title = 21
        padding_horizontal = 8
        padding_vertical = 8
        padding_card_h = 12
        padding_card_v = 10
        chip_font_size = 11
        input_font_size = 13
        gap_header_body = 8
        gap_body_composer = 8
        logo_size_header = 34
        logo_size_hero = 48
        avatar_size = 30
    else:
        size_category = "full"
        top_padding = 50
        font_size_title = 17
        font_size_subtitle = 10
        font_size_body = 13
        font_size_small = 11
        font_size_hero_title = 22
        padding_horizontal = 10
        padding_vertical = 10
        padding_card_h = 14
        padding_card_v = 12
        chip_font_size = 11
        input_font_size = 13
        gap_header_body = 10
        gap_body_composer = 10
        logo_size_header = 36
        logo_size_hero = 50
        avatar_size = 32

    return _base_config(
        width=width,
        height=height,
        is_mobile=True,
        is_ios=True,
        is_android=False,
        compact=compact,
        sidebar_visible=False,
        top_padding=top_padding + 6,
        font_size_title=font_size_title,
        font_size_subtitle=font_size_subtitle,
        font_size_body=font_size_body,
        font_size_small=font_size_small,
        font_size_hero_title=font_size_hero_title,
        font_size_splash_title=26 if size_category != "se" else 20,
        font_size_splash_sub=14 if size_category != "se" else 12,
        font_size_splash_body=12 if size_category != "se" else 11,
        padding_horizontal=padding_horizontal,
        padding_vertical=padding_vertical,
        padding_card_h=padding_card_h,
        padding_card_v=padding_card_v,
        button_height=48,
        logo_size_header=logo_size_header,
        logo_size_hero=logo_size_hero,
        avatar_size=avatar_size,
        input_font_size=input_font_size,
        chip_font_size=chip_font_size,
        gap_header_body=gap_header_body,
        gap_body_composer=gap_body_composer,
        drawer_width=min(width * 0.84, 320),
        splash_card_width=width * 0.92,
        splash_padding_h=18 if size_category != "se" else 14,
        splash_padding_v=18 if size_category != "se" else 14,
        orb_size_top=200 if size_category != "se" else 140,
        orb_size_bottom=150 if size_category != "se" else 120,
    )


def _mobile_web_config(width: float, height: float) -> LayoutConfig:
    compact = width < 380
    top_padding = max(_android_safe_top(height), _ios_safe_top(height))

    return _base_config(
        width=width,
        height=height,
        is_mobile=True,
        is_ios=False,
        is_android=False,
        compact=compact,
        sidebar_visible=False,
        top_padding=top_padding,
        font_size_title=15 if compact else 17,
        font_size_subtitle=9,
        font_size_body=12 if compact else 13,
        font_size_small=10,
        font_size_hero_title=20 if compact else 22,
        font_size_splash_title=22 if compact else 28,
        font_size_splash_sub=12 if compact else 14,
        font_size_splash_body=11 if compact else 12,
        padding_horizontal=6 if compact else 8,
        padding_vertical=6 if compact else 8,
        padding_card_h=10 if compact else 12,
        padding_card_v=8 if compact else 10,
        button_height=48,
        logo_size_header=32 if compact else 36,
        logo_size_hero=44 if compact else 50,
        avatar_size=30 if compact else 32,
        input_font_size=12 if compact else 13,
        chip_font_size=10 if compact else 11,
        gap_header_body=6 if compact else 8,
        gap_body_composer=6 if compact else 8,
        drawer_width=min(width * 0.84, 320),
        splash_card_width=width * 0.92,
        splash_padding_h=14 if compact else 18,
        splash_padding_v=14 if compact else 18,
        orb_size_top=200 if compact else 240,
        orb_size_bottom=150 if compact else 180,
    )


def _splash_title_size(width: float) -> int:
    if width >= 1300:
        return 54
    if width >= 1000:
        return 48
    if width >= 760:
        return 40
    return 28


def _splash_body_size(width: float) -> int:
    if width >= 1100:
        return 16
    if width >= 820:
        return 14
    return 12


def _splash_card_width(width: float) -> float:
    if width >= 1400:
        return 980
    if width >= 1200:
        return 900
    if width >= 980:
        return 820
    return width * 0.92

