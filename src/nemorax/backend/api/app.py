"""FastAPI application factory."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from time import perf_counter
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from nemorax.backend.api.routes import auth, chat, feedback, health, history, users
from nemorax.backend.core.errors import ApplicationError
from nemorax.backend.core.logging import configure_logging, get_logger
from nemorax.backend.core.settings import settings
from nemorax.backend.runtime import ApplicationServices, get_runtime_services
from nemorax.backend.services.rag import build_index


configure_logging(settings.log_level)
logger = get_logger("nemorax.api")


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
        rag_task: asyncio.Task[None] | None = None
        if resolved_services.settings.environment != "test":
            async def warm_rag_index() -> None:
                try:
                    await asyncio.to_thread(build_index)
                except Exception as exc:
                    logger.exception("Background RAG index build failed", exc_info=exc)

            rag_task = asyncio.create_task(warm_rag_index())
        yield
        if rag_task is not None and not rag_task.done():
            rag_task.cancel()
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
        allow_origins=resolved_services.settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_timing_middleware(request: Request, call_next):
        started = perf_counter()
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        response = await call_next(request)
        response.headers["X-Process-Time"] = f"{perf_counter() - started:.4f}"
        response.headers["X-Request-ID"] = request_id
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": exc.errors()})

    @app.exception_handler(ApplicationError)
    async def application_exception_handler(_: Request, exc: ApplicationError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled backend exception", exc_info=exc)
        return JSONResponse(status_code=500, content={"detail": "Internal server error."})

    app.include_router(auth.router)
    app.include_router(users.router)
    app.include_router(chat.router)
    app.include_router(history.router)
    app.include_router(feedback.router)
    app.include_router(health.router)
    return app


app = create_app()
