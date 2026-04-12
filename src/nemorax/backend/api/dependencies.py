"""FastAPI dependency providers."""

from __future__ import annotations

from fastapi import Request

from nemorax.backend.runtime import ApplicationServices, get_runtime_services


def get_services(request: Request) -> ApplicationServices:
    services = getattr(request.app.state, "services", None)
    if services is None:
        services = get_runtime_services()
        request.app.state.services = services
    return services
