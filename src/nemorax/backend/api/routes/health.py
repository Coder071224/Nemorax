"""Health and runtime metadata routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from nemorax.backend.api.dependencies import get_services
from nemorax.backend.runtime import ApplicationServices
from nemorax.backend.schemas import HealthResponse


router = APIRouter(tags=["health"])


@router.get("/api/health", response_model=HealthResponse)
async def health(services: ApplicationServices = Depends(get_services)) -> HealthResponse:
    return HealthResponse(**(await services.chat_service.health()))
