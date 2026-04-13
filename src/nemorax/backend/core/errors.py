"""Application-specific error types for the Nemorax backend."""

from __future__ import annotations


class ApplicationError(Exception):
    """Base application error with an HTTP status mapping."""

    status_code = 400


class ValidationError(ApplicationError):
    """Raised when user input is valid JSON but invalid business input."""

    status_code = 400


class AuthenticationError(ApplicationError):
    """Raised when authentication fails."""

    status_code = 401


class NotFoundError(ApplicationError):
    """Raised when a requested record cannot be found."""

    status_code = 404


class ConflictError(ApplicationError):
    """Raised when a resource already exists or conflicts."""

    status_code = 409


class ConfigurationError(ApplicationError):
    """Raised when required runtime configuration is missing or invalid."""

    status_code = 500


class PersistenceError(ApplicationError):
    """Raised when persistent storage cannot be read or written safely."""

    status_code = 500


class LLMConnectionError(ApplicationError):
    """Raised when the configured model provider cannot be reached."""

    status_code = 503


class LLMResponseError(ApplicationError):
    """Raised when a model provider returns an invalid or failed response."""

    status_code = 502
