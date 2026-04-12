"""Authentication routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from nemorax.backend.api.dependencies import get_services
from nemorax.backend.core.errors import NotFoundError
from nemorax.backend.runtime import ApplicationServices
from nemorax.backend.schemas import (
    AuthResponse,
    LoginRequest,
    RecoveryQuestionsRequest,
    RecoveryQuestionsResponse,
    RegisterRequest,
    ResetPasswordRequest,
    VerifyRecoveryRequest,
)


router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=AuthResponse)
async def register(req: RegisterRequest, services: ApplicationServices = Depends(get_services)) -> AuthResponse:
    message = services.auth_service.register_user(req.email, req.password, req.recovery_answers)
    return AuthResponse(success=True, message=message)


@router.post("/login", response_model=AuthResponse)
async def login(req: LoginRequest, services: ApplicationServices = Depends(get_services)) -> AuthResponse:
    user, message = services.auth_service.login_user(req.email, req.password)
    return AuthResponse(
        success=True,
        message=message,
        user_id=user["user_id"],
        email=user["email"],
        display_name=user.get("display_name"),
        settings=user.get("settings", {}),
    )


@router.post("/recovery/questions", response_model=RecoveryQuestionsResponse)
async def recovery_questions(
    req: RecoveryQuestionsRequest,
    services: ApplicationServices = Depends(get_services),
) -> RecoveryQuestionsResponse:
    questions = services.auth_service.get_recovery_questions(req.email)
    if not questions:
        raise NotFoundError("No account found for this email.")
    return RecoveryQuestionsResponse(email=req.email, questions=questions)


@router.post("/recovery/verify", response_model=AuthResponse)
async def verify_recovery(
    req: VerifyRecoveryRequest,
    services: ApplicationServices = Depends(get_services),
) -> AuthResponse:
    message = services.auth_service.verify_recovery_answers(req.email, req.answers)
    return AuthResponse(success=True, message=message)


@router.post("/recovery/reset", response_model=AuthResponse)
async def reset_password(
    req: ResetPasswordRequest,
    services: ApplicationServices = Depends(get_services),
) -> AuthResponse:
    message = services.auth_service.reset_password(req.email, req.new_password)
    return AuthResponse(success=True, message=message)
