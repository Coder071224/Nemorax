"""FastAPI application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager
from time import perf_counter
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from nemorax.backend.api.routes import auth, chat, feedback, health, history, users
from nemorax.backend.core.errors import (
    ApplicationError,
    AuthenticationError,
    ConfigurationError,
    ConflictError,
    LLMConnectionError,
    LLMResponseError,
    NotFoundError,
    PersistenceError,
    ValidationError,
)
from nemorax.backend.core.logging import configure_logging, get_logger
from nemorax.backend.core.settings import settings
from nemorax.backend.runtime import ApplicationServices, get_runtime_services
from nemorax.backend.schemas import ApiErrorPayload, ApiResponse


configure_logging(settings.log_level)
logger = get_logger("nemorax.api")


def _error_code_for_status(status_code: int) -> str:
    return {
        401: "auth_error",
        403: "permission_error",
        404: "not_found",
        409: "conflict_error",
        422: "validation_error",
        429: "rate_limit_error",
        502: "upstream_error",
        503: "temporary_failure",
    }.get(status_code, "internal_error" if status_code >= 500 else "request_error")


def _error_code_for_exception(exc: ApplicationError) -> str:
    mappings: list[tuple[type[ApplicationError], str]] = [
        (ValidationError, "validation_error"),
        (AuthenticationError, "auth_error"),
        (NotFoundError, "not_found"),
        (ConflictError, "conflict_error"),
        (LLMConnectionError, "temporary_failure"),
        (LLMResponseError, "upstream_error"),
        (ConfigurationError, "configuration_error"),
        (PersistenceError, "persistence_error"),
    ]
    for error_type, code in mappings:
        if isinstance(exc, error_type):
            return code
    return _error_code_for_status(exc.status_code)


def _error_response(
    *,
    status_code: int,
    request: Request,
    message: str,
    code: str | None = None,
    details: object | None = None,
) -> JSONResponse:
    payload = ApiResponse[object](
        ok=False,
        error=ApiErrorPayload(
            code=code or _error_code_for_status(status_code),
            message=message,
            details=details,
            request_id=getattr(request.state, "request_id", None),
        ),
    )
    return JSONResponse(status_code=status_code, content=payload.model_dump())


def _cors_options(services: ApplicationServices) -> dict[str, object]:
    return {
        "allow_origins": services.settings.cors_origins,
        "allow_credentials": services.settings.api.cors_allow_credentials,
        "allow_methods": ["GET", "POST", "DELETE", "OPTIONS"],
        "allow_headers": ["*"],
    }


def create_app(*, services: ApplicationServices | None = None) -> FastAPI:
    resolved_services = services or get_runtime_services()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        resolved_services.ensure_ready()
        logger.info(
            "Starting Nemorax backend with provider=%s model=%s",
            resolved_services.llm_provider.name,
            resolved_services.llm_provider.model,
        )
        yield
        logger.info("Stopping Nemorax backend")

    app = FastAPI(
        title=resolved_services.settings.app_name,
        version=resolved_services.settings.app_version,
        description="Nemorax backend API.",
        lifespan=lifespan,
    )
    app.state.services = resolved_services
    app.add_middleware(
        CORSMiddleware,
        **_cors_options(resolved_services),
    )

    @app.middleware("http")
    async def request_timing_middleware(request: Request, call_next):
        started = perf_counter()
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Process-Time"] = f"{perf_counter() - started:.4f}"
        response.headers["X-Request-ID"] = request_id
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        return _error_response(
            status_code=422,
            request=request,
            message="The request payload is invalid.",
            code="validation_error",
            details=exc.errors(),
        )

    @app.exception_handler(ApplicationError)
    async def application_exception_handler(request: Request, exc: ApplicationError) -> JSONResponse:
        return _error_response(
            status_code=exc.status_code,
            request=request,
            message=str(exc),
            code=_error_code_for_exception(exc),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled backend exception", exc_info=exc)
        return _error_response(
            status_code=500,
            request=request,
            message="Internal server error.",
            code="internal_error",
        )

    app.include_router(auth.router)
    app.include_router(users.router)
    app.include_router(chat.router)
    app.include_router(history.router)
    app.include_router(feedback.router)
    app.include_router(health.router)
    return app


app = create_app()
