"""Frontend time helpers anchored to Asia/Manila."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


try:
    PH_TZ = ZoneInfo("Asia/Manila")
except ZoneInfoNotFoundError:
    PH_TZ = timezone(timedelta(hours=8), name="Asia/Manila")


def ph_now() -> datetime:
    return datetime.now(timezone.utc).astimezone(PH_TZ)


def parse_backend_datetime(value: str | None) -> datetime:
    if not value:
        return ph_now()

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return ph_now()

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(PH_TZ)
