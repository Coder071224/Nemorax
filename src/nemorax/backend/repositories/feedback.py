"""Supabase-backed feedback repository."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from nemorax.backend.repositories.supabase_client import SupabasePersistenceClient
from nemorax.backend.schemas import FeedbackRequest, FeedbackResponse


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class FeedbackRepository:
    def __init__(self, client: SupabasePersistenceClient) -> None:
        self._client = client

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
        self._client.insert("feedback_records", payload, returning="minimal")
        return FeedbackResponse(feedback_id=feedback_id, saved_at=saved_at)

    def list(self, limit: int = 100, user_id: str | None = None) -> list[dict[str, Any]]:
        filters: dict[str, tuple[str, str] | str] = {}
        if user_id is not None:
            filters["user_id"] = user_id
        rows = self._client.select(
            "feedback_records",
            filters=filters or None,
            order="saved_at.desc",
            limit=limit,
        )
        return rows

    def import_feedback(self, entry: dict[str, Any]) -> FeedbackResponse | None:
        feedback_id = str(entry.get("feedback_id", "")).strip() or str(uuid.uuid4())
        saved_at = str(entry.get("saved_at", "")).strip() or _now_iso()
        payload = {
            "feedback_id": feedback_id,
            "session_id": entry.get("session_id"),
            "rating": entry.get("rating"),
            "comment": str(entry.get("comment", "") or ""),
            "category": entry.get("category"),
            "user_id": entry.get("user_id"),
            "saved_at": saved_at,
        }
        self._client.upsert("feedback_records", payload, on_conflict="feedback_id", returning="minimal")
        return FeedbackResponse(feedback_id=feedback_id, saved_at=saved_at)
