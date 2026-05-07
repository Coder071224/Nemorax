"""Per-page frontend state shared by UI builders."""
from __future__ import annotations

from dataclasses import dataclass

from nemorax.frontend.config import DEFAULT_THEME, THEMES, ThemePalette, apply_theme


@dataclass
class AppState:
    """Live UI state for one Flet page/session.

    Persistence lives in backend settings or client storage. This object is the
    in-memory source used while controls are being rebuilt.
    """

    active_theme_name: str = DEFAULT_THEME

    def set_theme(self, name: str | None) -> ThemePalette:
        self.active_theme_name = name if name in THEMES else DEFAULT_THEME
        return apply_theme(self.active_theme_name)

    def activate_theme(self) -> ThemePalette:
        return apply_theme(self.active_theme_name)
