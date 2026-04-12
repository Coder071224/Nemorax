from __future__ import annotations

import flet as ft


_DESKTOP_PLATFORMS = {
    ft.PagePlatform.WINDOWS,
    ft.PagePlatform.MACOS,
    ft.PagePlatform.LINUX,
    ft.PagePlatform.WEB,
}


def _num(value, fallback: float) -> float:
    try:
        n = float(value)
        if n > 0:
            return n
    except Exception:
        pass
    return float(fallback)


def _page_size(page: ft.Page) -> tuple[float, float]:
    width = _num(page.width or getattr(page, "window_width", None), 1320)
    height = _num(page.height or getattr(page, "window_height", None), 860)
    return max(width, 320.0), max(height, 568.0)


def _ios_safe_top(height: float) -> int:
    """
    Conservative notch / Dynamic Island spacing heuristic.
    """
    if height < 700:
        return 20
    if height < 800:
        return 44
    if height < 871:
        return 52
    return 58


def get_layout_config(page: ft.Page) -> dict:
    width, height = _page_size(page)
    platform = page.platform

    is_desktop_web = platform in _DESKTOP_PLATFORMS
    is_android = platform == ft.PagePlatform.ANDROID

    if is_desktop_web:
        return {
            "platform_group": "desktop_web",
            "platform": str(platform),
            "page_width": width,
            "page_height": height,
            "is_desktop_web": True,
            "is_android": False,
            "is_ios": False,
            "is_mobile": False,
            "mobile_tier": "desktop",
            "safe_top_padding": 0,
            "top_padding": 0,
            "outer_padding": 24,
            "padding_horizontal": 24,
            "padding_vertical": 20,
            "section_gap": 18,
            "page_max_width": 1280,
            "shell_width": min(width - 48, 1180),
            "centered_shell": True,
            "sidebar_visible": True,
            "sidebar_expanded_width": 272,
            "sidebar_collapsed_width": 76,
            "settings_panel_width": 360,
            "drawer_width": 0,
            "font_size_title": 28,
            "font_size_heading": 24,
            "font_size_subtitle": 12.5,
            "font_size_body": 14,
            "font_size_body_small": 12,
            "font_size_caption": 11,
            "font_size_chip": 12,
            "button_height": 46,
            "min_tap_target": 46,
            "icon_button_size": 42,
            "input_min_height": 52,
            "dialog_width": min(width - 60, 440),
            "dialog_padding": 24,
            "dialog_radius": 28,
            "card_radius_xl": 28,
            "card_radius_lg": 20,
            "card_radius_md": 16,
            "splash_card_width": (
                1080 if width >= 1600 else
                980 if width >= 1300 else
                900 if width >= 1100 else
                820 if width >= 900 else
                max(320, width * 0.92)
            ),
            "splash_orb_top": 420,
            "splash_orb_bottom": 320,
            "splash_title_size": (
                56 if width >= 1300 else
                48 if width >= 1000 else
                40 if width >= 760 else
                28
            ),
            "splash_subtitle_size": 18,
            "splash_body_size": 16 if width >= 1100 else 14 if width >= 820 else 12,
            "splash_card_pad_x": 36,
            "splash_card_pad_y": 28,
            "message_avatar_size": 34,
            "message_meta_size": 11,
            "message_text_size": 14,
            "bubble_pad_h": 16,
            "bubble_pad_v": 12,
            "bubble_gap": 10,
        }

    if is_android:
        compact = width < 380
        return {
            "platform_group": "android",
            "platform": str(platform),
            "page_width": width,
            "page_height": height,
            "is_desktop_web": False,
            "is_android": True,
            "is_ios": False,
            "is_mobile": True,
            "mobile_tier": "compact" if compact else "standard",
            "safe_top_padding": 10,
            "top_padding": 14 if compact else 16,
            "outer_padding": 10 if compact else 12,
            "padding_horizontal": 12 if compact else 14,
            "padding_vertical": 10 if compact else 12,
            "section_gap": 10 if compact else 12,
            "page_max_width": width,
            "shell_width": width,
            "centered_shell": False,
            "sidebar_visible": False,
            "sidebar_expanded_width": 0,
            "sidebar_collapsed_width": 0,
            "settings_panel_width": min(width - 24, 360),
            "drawer_width": min(width * 0.88, 320),
            "font_size_title": 18 if compact else 20,
            "font_size_heading": 20 if compact else 22,
            "font_size_subtitle": 9.5 if compact else 10.5,
            "font_size_body": 12 if compact else 13,
            "font_size_body_small": 10.5 if compact else 11,
            "font_size_caption": 10,
            "font_size_chip": 11 if compact else 12,
            "button_height": 48,
            "min_tap_target": 48,
            "icon_button_size": 48,
            "input_min_height": 50 if compact else 52,
            "dialog_width": min(width - 12, 420),
            "dialog_padding": 18 if compact else 20,
            "dialog_radius": 24,
            "card_radius_xl": 24,
            "card_radius_lg": 18,
            "card_radius_md": 14,
            "splash_card_width": max(304, width - (24 if compact else 28)),
            "splash_orb_top": 220 if compact else 250,
            "splash_orb_bottom": 170 if compact else 190,
            "splash_title_size": 28 if compact else 30,
            "splash_subtitle_size": 13 if compact else 14,
            "splash_body_size": 11.5 if compact else 12.5,
            "splash_card_pad_x": 18 if compact else 22,
            "splash_card_pad_y": 16 if compact else 18,
            "message_avatar_size": 32 if compact else 34,
            "message_meta_size": 10 if compact else 10.5,
            "message_text_size": 12.5 if compact else 13.5,
            "bubble_pad_h": 12 if compact else 14,
            "bubble_pad_v": 10 if compact else 11,
            "bubble_gap": 8 if compact else 10,
        }

    if height < 700:
        tier = "compact"
        pad_x = 12
        pad_y = 10
        title = 18
        heading = 20
        subtitle = 10
        body = 12
        body_small = 10.5
        splash_top = 220
        splash_bottom = 165
        splash_pad_x = 18
        splash_pad_y = 16
    elif height < 871:
        tier = "standard"
        pad_x = 14
        pad_y = 12
        title = 20
        heading = 22
        subtitle = 10.5
        body = 13
        body_small = 11
        splash_top = 250
        splash_bottom = 185
        splash_pad_x = 22
        splash_pad_y = 18
    else:
        tier = "full"
        pad_x = 16
        pad_y = 14
        title = 21
        heading = 23
        subtitle = 11
        body = 13.5
        body_small = 11.5
        splash_top = 270
        splash_bottom = 200
        splash_pad_x = 24
        splash_pad_y = 20

    safe_top = _ios_safe_top(height)
    return {
        "platform_group": "ios",
        "platform": str(platform),
        "page_width": width,
        "page_height": height,
        "is_desktop_web": False,
        "is_android": False,
        "is_ios": True,
        "is_mobile": True,
        "mobile_tier": tier,
        "safe_top_padding": safe_top,
        "top_padding": safe_top + 8,
        "outer_padding": 12 if tier == "compact" else 14,
        "padding_horizontal": pad_x,
        "padding_vertical": pad_y,
        "section_gap": 10 if tier == "compact" else 12 if tier == "standard" else 14,
        "page_max_width": width,
        "shell_width": width,
        "centered_shell": False,
        "sidebar_visible": False,
        "sidebar_expanded_width": 0,
        "sidebar_collapsed_width": 0,
        "settings_panel_width": min(width - 20, 380),
        "drawer_width": min(width * 0.88, 332),
        "font_size_title": title,
        "font_size_heading": heading,
        "font_size_subtitle": subtitle,
        "font_size_body": body,
        "font_size_body_small": body_small,
        "font_size_caption": 10.5,
        "font_size_chip": 11.5,
        "button_height": 50,
        "min_tap_target": 48,
        "icon_button_size": 48,
        "input_min_height": 52,
        "dialog_width": min(width - 12, 430),
        "dialog_padding": 20,
        "dialog_radius": 26,
        "card_radius_xl": 26,
        "card_radius_lg": 18,
        "card_radius_md": 14,
        "splash_card_width": max(304, width - (24 if tier == "compact" else 28 if tier == "standard" else 32)),
        "splash_orb_top": splash_top,
        "splash_orb_bottom": splash_bottom,
        "splash_title_size": 30 if tier == "compact" else 32 if tier == "standard" else 34,
        "splash_subtitle_size": 14 if tier == "compact" else 15,
        "splash_body_size": 12 if tier == "compact" else 12.5 if tier == "standard" else 13,
        "splash_card_pad_x": splash_pad_x,
        "splash_card_pad_y": splash_pad_y,
        "message_avatar_size": 34,
        "message_meta_size": 10.5,
        "message_text_size": 13 if tier == "compact" else 13.5,
        "bubble_pad_h": 14,
        "bubble_pad_v": 11,
        "bubble_gap": 10,
    }

