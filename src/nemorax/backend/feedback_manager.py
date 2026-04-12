"""Compatibility wrapper around the feedback service."""

from __future__ import annotations

from typing import Any

from nemorax.backend.runtime import get_runtime_services
from nemorax.backend.schemas import FeedbackRequest, FeedbackResponse


def save_feedback(request: FeedbackRequest) -> FeedbackResponse:
    return get_runtime_services().feedback_service.save_feedback(request)


def list_feedback(limit: int = 100, user_id: str | None = None) -> list[dict[str, Any]]:
    return get_runtime_services().feedback_service.list_feedback(limit=limit, user_id=user_id)
