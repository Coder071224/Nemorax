"""Chat routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from nemorax.backend.api.dependencies import get_services
from nemorax.backend.core.errors import ValidationError
from nemorax.backend.runtime import ApplicationServices
from nemorax.backend.schemas import ChatRequest, ChatResponse


router = APIRouter(tags=["chat"])


@router.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, services: ApplicationServices = Depends(get_services)) -> ChatResponse:
    if not req.messages:
        raise ValidationError("messages list is empty")
    return await services.chat_service.chat(req)
