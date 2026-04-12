"""File-backed feedback repository."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any

from nemorax.backend.core.settings import PathSettings
from nemorax.backend.repositories.json_store import read_json_object, write_json_atomic
from nemorax.backend.schemas import FeedbackRequest, FeedbackResponse


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class FeedbackRepository:
    def __init__(self, paths: PathSettings) -> None:
        self._feedback_dir = paths.feedback_dir
        self._lock = RLock()

    def _path(self, feedback_id: str) -> Path:
        return self._feedback_dir / f"{feedback_id}.json"

    def save(self, request: FeedbackRequest) -> FeedbackResponse:
        feedback_id = str(uuid.uuid4())
        saved_at = _now_iso()
        payload = {
            "feedback_id": feedback_id,
            "session_id": request.session_id,
            "rating": request.rating,
            "comment": request.comment,
            "category": request.category,
            "user_id": request.user_id,
            "saved_at": saved_at,
        }
        with self._lock:
            write_json_atomic(self._path(feedback_id), payload)
        return FeedbackResponse(feedback_id=feedback_id, saved_at=saved_at)

    def list(self, limit: int = 100, user_id: str | None = None) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for path in self._feedback_dir.glob("*.json"):
            entry = read_json_object(path)
            if entry is None:
                continue
            if user_id is not None and entry.get("user_id") != user_id:
                continue
            entries.append(entry)

        entries.sort(key=lambda item: str(item.get("saved_at", "")), reverse=True)
        return entries[:limit]
