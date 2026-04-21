"""Health and runtime metadata routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from nemorax.backend.api.dependencies import get_services
from nemorax.backend.runtime import ApplicationServices
from nemorax.backend.schemas import ApiResponse, HealthResponse


router = APIRouter(tags=["health"])


@router.get("/api/health", response_model=ApiResponse[HealthResponse])
async def health(services: ApplicationServices = Depends(get_services)) -> ApiResponse[HealthResponse]:
    return ApiResponse(ok=True, data=HealthResponse(**(await services.chat_service.health())))
