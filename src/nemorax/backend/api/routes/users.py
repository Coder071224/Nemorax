"""User profile and settings routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from nemorax.backend.api.dependencies import get_services
from nemorax.backend.core.errors import NotFoundError
from nemorax.backend.runtime import ApplicationServices
from nemorax.backend.schemas import (
    ApiResponse,
    DisplayNameUpdateRequest,
    SettingsUpdateRequest,
    UserSettingsResponse,
    UserProfileResponse,
)


router = APIRouter(tags=["users"])


@router.get("/api/users/{user_id}", response_model=ApiResponse[UserProfileResponse])
async def get_user_profile(
    user_id: str,
    services: ApplicationServices = Depends(get_services),
) -> ApiResponse[UserProfileResponse]:
    profile = services.auth_service.get_public_user(user_id)
    if profile is None:
        raise NotFoundError("User not found")
    return ApiResponse(ok=True, data=UserProfileResponse(**profile))


@router.post("/api/users/{user_id}/display-name", response_model=ApiResponse[UserProfileResponse])
async def save_display_name(
    user_id: str,
    body: DisplayNameUpdateRequest,
    services: ApplicationServices = Depends(get_services),
) -> ApiResponse[UserProfileResponse]:
    profile = services.auth_service.update_display_name(user_id, body.display_name)
    return ApiResponse(ok=True, data=UserProfileResponse(**profile))


@router.get("/api/settings/{user_id}", response_model=ApiResponse[UserSettingsResponse])
async def get_settings(user_id: str, services: ApplicationServices = Depends(get_services)) -> ApiResponse[UserSettingsResponse]:
    return ApiResponse(ok=True, data=UserSettingsResponse(settings=services.auth_service.read_user_settings(user_id)))


@router.post("/api/settings/{user_id}", response_model=ApiResponse[UserSettingsResponse])
async def save_settings(
    user_id: str,
    body: SettingsUpdateRequest,
    services: ApplicationServices = Depends(get_services),
) -> ApiResponse[UserSettingsResponse]:
    return ApiResponse(
        ok=True,
        data=UserSettingsResponse(settings=services.auth_service.update_user_settings(user_id, body.to_dict())),
    )
