"""Compatibility entrypoint for the FastAPI backend."""

from nemorax.backend.api.app import app, create_app

__all__ = ["app", "create_app"]
