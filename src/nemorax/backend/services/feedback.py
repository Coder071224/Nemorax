"""Feedback service."""

from __future__ import annotations

from typing import Any

from nemorax.backend.repositories.feedback import FeedbackRepository
from nemorax.backend.schemas import FeedbackRequest, FeedbackResponse


class FeedbackService:
    def __init__(self, feedback_repository: FeedbackRepository) -> None:
        self._feedback = feedback_repository

    def save_feedback(self, request: FeedbackRequest) -> FeedbackResponse:
        return self._feedback.save(request)

    def list_feedback(self, limit: int = 100, user_id: str | None = None) -> list[dict[str, Any]]:
        return self._feedback.list(limit=limit, user_id=user_id)
