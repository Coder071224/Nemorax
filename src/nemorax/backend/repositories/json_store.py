"""Shared JSON file helpers for file-backed repositories."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from nemorax.backend.core.logging import get_logger
from nemorax.backend.core.errors import PersistenceError


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


def write_json_atomic(path: Path, payload: JsonObject) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f"{path.suffix}.tmp")

    try:
        temp_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        temp_path.replace(path)
    except OSError as exc:
        raise PersistenceError(f"Unable to write {path.name}.") from exc
