"""Authentication routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from nemorax.backend.api.dependencies import get_services
from nemorax.backend.core.errors import NotFoundError
from nemorax.backend.runtime import ApplicationServices
from nemorax.backend.schemas import (
    ApiResponse,
    AuthResponse,
    LoginRequest,
    RecoveryQuestionsRequest,
    RecoveryQuestionsResponse,
    RegisterRequest,
    ResetPasswordRequest,
    VerifyRecoveryRequest,
)


router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=ApiResponse[AuthResponse])
async def register(req: RegisterRequest, services: ApplicationServices = Depends(get_services)) -> ApiResponse[AuthResponse]:
    message = services.auth_service.register_user(req.email, req.password, req.recovery_answers)
    return ApiResponse(ok=True, data=AuthResponse(message=message))


@router.post("/login", response_model=ApiResponse[AuthResponse])
async def login(req: LoginRequest, services: ApplicationServices = Depends(get_services)) -> ApiResponse[AuthResponse]:
    user, message = services.auth_service.login_user(req.email, req.password)
    return ApiResponse(
        ok=True,
        data=AuthResponse(
            message=message,
            user_id=user["user_id"],
            email=user["email"],
            display_name=user.get("display_name"),
            settings=user.get("settings", {}),
        ),
    )


@router.post("/recovery/questions", response_model=ApiResponse[RecoveryQuestionsResponse])
async def recovery_questions(
    req: RecoveryQuestionsRequest,
    services: ApplicationServices = Depends(get_services),
) -> ApiResponse[RecoveryQuestionsResponse]:
    questions = services.auth_service.get_recovery_questions(req.email)
    if not questions:
        raise NotFoundError("No account found for this email.")
    return ApiResponse(ok=True, data=RecoveryQuestionsResponse(email=req.email, questions=questions))


@router.post("/recovery/verify", response_model=ApiResponse[AuthResponse])
async def verify_recovery(
    req: VerifyRecoveryRequest,
    services: ApplicationServices = Depends(get_services),
) -> ApiResponse[AuthResponse]:
    message = services.auth_service.verify_recovery_answers(req.email, req.answers)
    return ApiResponse(ok=True, data=AuthResponse(message=message))


@router.post("/recovery/reset", response_model=ApiResponse[AuthResponse])
async def reset_password(
    req: ResetPasswordRequest,
    services: ApplicationServices = Depends(get_services),
) -> ApiResponse[AuthResponse]:
    message = services.auth_service.reset_password(req.email, req.new_password)
    return ApiResponse(ok=True, data=AuthResponse(message=message))
