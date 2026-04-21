"""Chat routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from nemorax.backend.api.dependencies import get_services
from nemorax.backend.core.errors import NotFoundError, ValidationError
from nemorax.backend.runtime import ApplicationServices
from nemorax.backend.schemas import ApiResponse, ChatRequest, ChatResponse, RetrievalPreviewRequest


router = APIRouter(tags=["chat"])


@router.post("/api/chat", response_model=ApiResponse[ChatResponse])
async def chat(req: ChatRequest, services: ApplicationServices = Depends(get_services)) -> ApiResponse[ChatResponse]:
    if not req.messages:
        raise ValidationError("messages list is empty")
    return ApiResponse(ok=True, data=await services.chat_service.chat(req))


@router.post("/api/chat/retrieval-preview", response_model=ApiResponse[dict[str, object]])
async def retrieval_preview(
    req: RetrievalPreviewRequest,
    services: ApplicationServices = Depends(get_services),
) -> ApiResponse[dict[str, object]]:
    if services.settings.environment == "production":
        raise NotFoundError("Not found")
    if not req.messages:
        raise ValidationError("messages list is empty")
    return ApiResponse(ok=True, data=services.chat_service.preview_retrieval(ChatRequest(**req.model_dump())))
