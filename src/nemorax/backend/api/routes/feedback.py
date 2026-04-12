"""Feedback routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from nemorax.backend.api.dependencies import get_services
from nemorax.backend.runtime import ApplicationServices
from nemorax.backend.schemas import FeedbackRequest, FeedbackResponse


router = APIRouter(tags=["feedback"])


@router.post("/api/feedback", response_model=FeedbackResponse)
async def submit_feedback(
    req: FeedbackRequest,
    services: ApplicationServices = Depends(get_services),
) -> FeedbackResponse:
    return services.feedback_service.save_feedback(req)
