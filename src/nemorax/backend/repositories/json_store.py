"""Shared JSON file helpers retained only for legacy data import/export."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from nemorax.backend.core.logging import get_logger
JsonObject = dict[str, Any]
logger = get_logger("nemorax.json_store")


def read_json_object(path: Path) -> JsonObject | None:
    if not path.exists():
        return None

    try:
        payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except OSError as exc:
        logger.warning("Failed to read JSON store %s: %s", path.as_posix(), exc)
        return None
    except json.JSONDecodeError as exc:
        logger.warning("Failed to decode JSON store %s: %s", path.as_posix(), exc)
        return None

    return payload if isinstance(payload, dict) else None
