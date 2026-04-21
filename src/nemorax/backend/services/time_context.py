"""Shared time-context rules for date-sensitive chat behavior."""

from __future__ import annotations

import re


CURRENT_CONTEXT_YEAR = 2026
CURRENT_CONTEXT_LABEL = str(CURRENT_CONTEXT_YEAR)
_TIME_SENSITIVE_PATTERN = re.compile(
    r"\b(current|currently|today|now|latest|recent|recently|up to date|up-to-date|as of)\b",
    re.IGNORECASE,
)


def is_time_sensitive_query(text: str | None) -> bool:
    return bool(_TIME_SENSITIVE_PATTERN.search((text or "").strip()))


def time_handling_instruction(*, bullet: bool = False) -> str:
    prefix = "- " if bullet else ""
    return (
        f"{prefix}Treat the present/current context as {CURRENT_CONTEXT_LABEL}. "
        "When the user asks for current, latest, recent, today, now, or similar wording, "
        "do not imply an older present. Prefer exact dates when relative phrasing could be ambiguous."
    )


def time_sensitive_fallback_guidance() -> str:
    return (
        f"If you mean current or latest information as of {CURRENT_CONTEXT_LABEL}, "
        "include the office, campus, program, or event so I can answer with the right date context."
    )

