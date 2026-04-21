"""
frontend/config.py
------------------
Frontend-only configuration.

No secrets live here. Backend URLs may be overridden by environment variables,
but all real secrets belong in backend/config.py or the deployment environment.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


LOCAL_BACKEND_URL = "http://127.0.0.1:8000"
_PRODUCTION_ENVIRONMENTS = {"production"}


def _normalize_api_url(value: str) -> str:
    return value.strip().rstrip("/")


def _environment_name() -> str:
    return os.getenv("NEMORAX_ENV", "development").strip().lower() or "development"


def _resolve_backend_url() -> str:
    configured = os.getenv("NEMORAX_API_URL", "").strip()
    if configured:
        return _normalize_api_url(configured)
    if _environment_name() in _PRODUCTION_ENVIRONMENTS:
        return ""
    return LOCAL_BACKEND_URL


_API_BASE_URL: str = _resolve_backend_url()

BRAND_NAME = "Nemorax"
APP_NAME = "Nemis"
CHATBOT_NAME = "Nemis"
USER_NAME = "User"
LOGO_ASSET = "Nemorax.png"

@dataclass(frozen=True)
class ThemePalette:
    name: str
    grad_top: str
    grad_mid: str
    grad_bottom: str
    sidebar_bg: str
    sidebar_card: str
    surface: str
    surface_alt: str
    user_bubble: str
    bot_bubble: str
    input_bg: str
    chip_bg: str
    send_btn: str
    text_primary: str
    text_secondary: str
    text_muted: str
    accent: str
    accent_soft: str
    success: str
    error: str
    border: str
    dialog_bg: str
    shadow: str


THEMES: dict[str, ThemePalette] = {
    "aurora_luxe": ThemePalette(
        name="Aurora Luxe",
        grad_top="#6ED6E2",
        grad_mid="#4B68C5",
        grad_bottom="#7A0BC0",
        sidebar_bg="#29115D",
        sidebar_card="#34196D",
        surface="#1F4E59B5",
        surface_alt="#2A6C3DBE",
        user_bubble="#3B69EA",
        bot_bubble="#47178E",
        input_bg="#365FD8",
        chip_bg="#3769D0",
        send_btn="#531E9F",
        text_primary="#F8FBFF",
        text_secondary="#C8D9FF",
        text_muted="#94A8DA",
        accent="#67E8F9",
        accent_soft="#3381F4FF",
        success="#6EE7B7",
        error="#FB7185",
        border="#40A8C2FF",
        dialog_bg="#271255",
        shadow="#090214",
    ),
    "royal_obsidian": ThemePalette(
        name="Royal Obsidian",
        grad_top="#161927",
        grad_mid="#1F2951",
        grad_bottom="#5E2A92",
        sidebar_bg="#0F1220",
        sidebar_card="#171C31",
        surface="#10FFFFFF",
        surface_alt="#1FA855F7",
        user_bubble="#315BDE",
        bot_bubble="#231441",
        input_bg="#172554",
        chip_bg="#243C8C",
        send_btn="#7C3AED",
        text_primary="#F8FAFC",
        text_secondary="#D6D9E6",
        text_muted="#9AA4BE",
        accent="#F5D76E",
        accent_soft="#2AF5D76E",
        success="#34D399",
        error="#FB7185",
        border="#24F8FAFC",
        dialog_bg="#111827",
        shadow="#000000",
    ),
    "glacier_pearl": ThemePalette(
        name="Glacier Pearl",
        grad_top="#D7F6F5",
        grad_mid="#AFCBFF",
        grad_bottom="#8790F0",
        sidebar_bg="#E8EEFF",
        sidebar_card="#F7F9FF",
        surface="#85FFFFFF",
        surface_alt="#B0E9EEFF",
        user_bubble="#4B6BEB",
        bot_bubble="#DEE7FF",
        input_bg="#EEF3FF",
        chip_bg="#D9E5FF",
        send_btn="#4B6BEB",
        text_primary="#16213E",
        text_secondary="#334A75",
        text_muted="#6B7EA8",
        accent="#1DB5CC",
        accent_soft="#1F1DB5CC",
        success="#10B981",
        error="#E11D48",
        border="#335D79C7",
        dialog_bg="#F7F9FF",
        shadow="#667085",
    ),
    "emerald_noir": ThemePalette(
        name="Emerald Noir",
        grad_top="#0F2E2A",
        grad_mid="#114E4A",
        grad_bottom="#2D1B69",
        sidebar_bg="#0D211F",
        sidebar_card="#13302D",
        surface="#80113A36",
        surface_alt="#703B1D79",
        user_bubble="#0F766E",
        bot_bubble="#26144F",
        input_bg="#0D5B54",
        chip_bg="#0E7066",
        send_btn="#6D28D9",
        text_primary="#F7FFFE",
        text_secondary="#C7EEE9",
        text_muted="#8FC3BC",
        accent="#6EE7B7",
        accent_soft="#336EE7B7",
        success="#34D399",
        error="#FB7185",
        border="#33D1FAE5",
        dialog_bg="#102826",
        shadow="#020B0A",
    ),
}

DEFAULT_THEME = "aurora_luxe"
DEFAULT_SHOW_SPLASH = True

SUGGESTED_QUESTIONS = [
    "How do I get my grades?",
    "What courses are available?",
    "How do I enroll?",
]

GENERIC_GREETING_NAMES = (
    "Night Owl",
    "Early Bird",
    "Wanderer",
    "Spark",
    "Deep Diver",
    "Pathfinder",
    "Bloom",
    "Drifter",
    "Thinker",
    "Free Spirit",
    "Campfire Soul",
    "Orbit",
    "Whirlwind",
    "Zen Mode",
    "Wildcard",
    "Transformer",
    "Connector",
    "Sharpshooter",
    "Summit Seeker",
    "Power User",
    "Rising Star",
    "Moonwalker",
    "Skimmer",
    "Broadcaster",
)


class _Colors:
    """Legacy compatibility placeholder for modules that may import Colors."""


Colors = _Colors()

_CURRENT_THEME: ThemePalette = THEMES[DEFAULT_THEME]


def normalize_user_settings(source: Any) -> dict[str, Any]:
    if isinstance(source, dict) and isinstance(source.get("settings"), dict):
        raw_settings = source.get("settings", {})
    elif isinstance(source, dict):
        raw_settings = source
    else:
        raw_settings = {}

    result: dict[str, Any] = {}

    theme = raw_settings.get("theme")
    if isinstance(theme, str) and theme in THEMES:
        result["theme"] = theme

    show_splash = raw_settings.get("show_splash")
    if isinstance(show_splash, bool):
        result["show_splash"] = show_splash

    return result


def get_api_base_url() -> str:
    return _API_BASE_URL


def has_api_base_url() -> bool:
    return bool(_API_BASE_URL)


def set_api_base_url(value: str | None) -> str:
    global _API_BASE_URL
    normalized = _normalize_api_url(value or "") if value else ""
    _API_BASE_URL = normalized
    return _API_BASE_URL


def resolve_theme_name(source: Any = None) -> str:
    settings = normalize_user_settings(source)
    theme = settings.get("theme")
    return theme if isinstance(theme, str) and theme in THEMES else DEFAULT_THEME


def should_show_splash(source: Any = None) -> bool:
    settings = normalize_user_settings(source)
    show_splash = settings.get("show_splash")
    return show_splash if isinstance(show_splash, bool) else DEFAULT_SHOW_SPLASH


def apply_theme(name: str) -> ThemePalette:
    global _CURRENT_THEME
    _CURRENT_THEME = THEMES.get(name, THEMES[DEFAULT_THEME])
    return _CURRENT_THEME


def current_theme() -> ThemePalette:
    return _CURRENT_THEME


apply_theme(DEFAULT_THEME)

