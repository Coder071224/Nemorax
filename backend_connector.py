# Requirements: httpx>=0.24.0  OR  aiohttp>=3.8.0, python-dotenv>=1.0.0
from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

try:
    import httpx
except ImportError:  # pragma: no cover - only used on minimal runtimes
    httpx = None  # type: ignore[assignment]

try:
    import aiohttp
except ImportError:  # pragma: no cover - only used on minimal runtimes
    aiohttp = None  # type: ignore[assignment]


PRIMARY_BACKEND_URL = os.getenv(
    "NEMIS_PRIMARY_BACKEND_URL",
    "https://nemis-backend.onrender.com",
).rstrip("/")
SECONDARY_BACKEND_URL = os.getenv(
    "NEMIS_SECONDARY_BACKEND_URL",
    "https://nemis-backend.up.railway.app",
).rstrip("/")

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "")

HEALTH_CHECK_TIMEOUT = 5.0
RENDER_WAKE_TIMEOUT = 20.0
RAILWAY_WAKE_TIMEOUT = 20.0
REQUEST_TIMEOUT = 30.0
HEALTH_ENDPOINTS = ("/api/health", "/health", "/ping", "/")

logger = logging.getLogger("nemis.backend")

_active_backend_url: str | None = None
_active_token: str | None = None
_backend_lock = asyncio.Lock()
_status_callback: Callable[[str], Any] | None = None


class BackendUnavailableError(Exception):
    """Raised when both configured backends are unreachable."""


class BackendTimeoutError(Exception):
    """Raised when an API request times out after a backend was selected."""


class AuthTokenMissingError(Exception):
    """Raised when a caller requires auth but no token has been configured."""


@dataclass(frozen=True)
class _BackendCandidate:
    name: str
    url: str
    wake_timeout: float


class _ColdStartError(Exception):
    """Internal marker for timeout/503 during health check."""


class _HealthCheckError(Exception):
    """Internal marker for non-recoverable health check failure."""


def set_status_callback(callback: Callable[[str], Any] | None) -> None:
    """Register an optional callback for UI status messages during wake retries."""

    global _status_callback
    _status_callback = callback


def set_auth_token(token: str | None) -> None:
    global _active_token
    normalized = token.strip() if isinstance(token, str) else ""
    _active_token = normalized or None


def clear_auth_token() -> None:
    global _active_token
    _active_token = None


def reset_backend_cache() -> None:
    """Clear the selected backend. Useful in tests or after a long offline period."""

    global _active_backend_url
    _active_backend_url = None


def get_supabase_headers() -> dict[str, str]:
    return {
        "apikey": SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {_active_token or SUPABASE_ANON_KEY}",
        "Content-Type": "application/json",
    }


async def get_backend_url() -> str:
    global _active_backend_url
    if _active_backend_url:
        return _active_backend_url

    async with _backend_lock:
        if _active_backend_url:
            return _active_backend_url

        render = _BackendCandidate("Render", PRIMARY_BACKEND_URL, RENDER_WAKE_TIMEOUT)
        railway = _BackendCandidate("Railway", SECONDARY_BACKEND_URL, RAILWAY_WAKE_TIMEOUT)

        if await _select_backend(render, primary=True):
            _active_backend_url = render.url
            logger.info("[Nemis] Connected to Render (primary backend).")
            return _active_backend_url

        logger.warning("[Nemis] Render is offline or unreachable. Switching to Railway...")

        if await _select_backend(railway, primary=False):
            _active_backend_url = railway.url
            logger.info("[Nemis] Using Railway as active backend.")
            return _active_backend_url

        logger.error("[Nemis] Both Render and Railway are unreachable.")
        raise BackendUnavailableError(
            "Both Render and Railway are unreachable. Please try again later."
        )


async def api_get(endpoint: str, **kwargs: Any) -> dict[str, Any]:
    return await _api_request("GET", endpoint, **kwargs)


async def api_post(endpoint: str, payload: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return await _api_request("POST", endpoint, json=payload, **kwargs)


async def _select_backend(candidate: _BackendCandidate, *, primary: bool) -> bool:
    try:
        await _check_backend_health(candidate.url, HEALTH_CHECK_TIMEOUT)
        logger.info("[Nemis] %s health check passed.", candidate.name)
        return True
    except _ColdStartError:
        logger.warning("[Nemis] %s appears to be waking up. Retrying once...", candidate.name)
        await _emit_status("Server is waking up. Please wait a few minutes, then log in again.")
        try:
            await _check_backend_health(candidate.url, candidate.wake_timeout)
            logger.info("[Nemis] %s health check passed after wake retry.", candidate.name)
            return True
        except (_ColdStartError, _HealthCheckError):
            logger.warning("[Nemis] %s wake retry failed.", candidate.name)
            return False
    except _HealthCheckError:
        level = logging.WARNING if primary else logging.ERROR
        logger.log(level, "[Nemis] %s health check failed.", candidate.name)
        return False


async def _check_backend_health(base_url: str, timeout: float) -> None:
    last_error: Exception | None = None
    for endpoint in HEALTH_ENDPOINTS:
        url = _join_url(base_url, endpoint)
        try:
            response = await _request("GET", url, timeout=timeout)
        except Exception as exc:
            if not _is_timeout_error(exc):
                last_error = exc
                logger.warning("[Nemis] Health check error for %s: %s", url, exc)
                continue
            logger.warning("[Nemis] Health check timeout for %s", url)
            raise _ColdStartError(str(exc)) from exc

        status_code = int(getattr(response, "status_code", 0))
        if 200 <= status_code <= 299:
            logger.info("[Nemis] Health check OK: %s", url)
            return
        if status_code == 503:
            logger.warning("[Nemis] Health check got 503 from %s", url)
            raise _ColdStartError(f"{url} returned 503")
        if status_code >= 500:
            logger.warning("[Nemis] Health check got %s from %s", status_code, url)
            raise _HealthCheckError(f"{url} returned {status_code}")

        last_error = _HealthCheckError(f"{url} returned {status_code}")
        logger.warning("[Nemis] Health endpoint rejected: %s returned %s", url, status_code)

    raise _HealthCheckError(str(last_error or "No health endpoint responded successfully"))


async def _api_request(method: str, endpoint: str, **kwargs: Any) -> dict[str, Any]:
    require_auth = bool(kwargs.pop("require_auth", False))
    if require_auth and not _active_token:
        raise AuthTokenMissingError("This endpoint requires auth but no token is set.")

    base_url = await get_backend_url()
    url = _join_url(base_url, endpoint)
    headers = _merge_headers(kwargs.pop("headers", None))
    timeout = float(kwargs.pop("timeout", REQUEST_TIMEOUT))

    try:
        response = await _request(method, url, headers=headers, timeout=timeout, **kwargs)
    except Exception as exc:
        if not _is_timeout_error(exc):
            raise
        logger.error("[Nemis] API request timed out: %s %s", method, url)
        raise BackendTimeoutError(f"Request timed out: {method} {endpoint}") from exc

    status_code = int(getattr(response, "status_code", 0))
    if status_code >= 500:
        logger.error("[Nemis] API request failed with %s: %s %s", status_code, method, url)
        raise BackendUnavailableError(f"Backend returned {status_code} for {endpoint}")
    if status_code < 200 or status_code > 299:
        logger.warning("[Nemis] API request returned %s: %s %s", status_code, method, url)

    return await _response_json(response)


async def _request(method: str, url: str, **kwargs: Any) -> Any:
    if httpx is not None:
        timeout = kwargs.pop("timeout", REQUEST_TIMEOUT)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            return await client.request(method, url, **kwargs)

    if aiohttp is None:  # pragma: no cover - depends on runtime packages
        raise RuntimeError("Install httpx>=0.24.0 or aiohttp>=3.8.0")

    timeout_value = float(kwargs.pop("timeout", REQUEST_TIMEOUT))
    headers = kwargs.pop("headers", None)
    json_payload = kwargs.pop("json", None)
    params = kwargs.pop("params", None)
    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=timeout_value)
    ) as session:
        async with session.request(
            method,
            url,
            headers=headers,
            json=json_payload,
            params=params,
            **kwargs,
        ) as response:
            return _AioHttpResponse(response.status, await response.text())


async def _response_json(response: Any) -> dict[str, Any]:
    if hasattr(response, "json"):
        data = response.json()
    else:
        data = response.data

    if asyncio.iscoroutine(data) or isinstance(data, Awaitable):
        data = await data

    if not isinstance(data, dict):
        return {"data": data}
    return data


def _merge_headers(headers: dict[str, str] | None) -> dict[str, str]:
    merged = dict(headers or {})
    if _active_token:
        merged["Authorization"] = f"Bearer {_active_token}"
    return merged


async def _emit_status(message: str) -> None:
    if _status_callback is None:
        return

    result = _status_callback(message)
    if asyncio.iscoroutine(result) or isinstance(result, Awaitable):
        await result


def _join_url(base_url: str, endpoint: str) -> str:
    base = base_url.rstrip("/")
    path = endpoint if endpoint.startswith("/") else f"/{endpoint}"
    return f"{base}{path}"


def _is_timeout_error(exc: Exception) -> bool:
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
        return True
    if httpx is not None and isinstance(exc, httpx.TimeoutException):
        return True
    if aiohttp is not None and isinstance(exc, asyncio.TimeoutError):
        return True
    return False


@dataclass
class _AioHttpResponse:
    status_code: int
    data: str

    def json(self) -> Any:
        import json

        return json.loads(self.data) if self.data else {}


# Loading screen integration example:
# from backend_connector import BackendUnavailableError, get_backend_url
# try:
#     url = await get_backend_url()
# except BackendUnavailableError as exc:
#     # show error state on loading screen
#     ...


if __name__ == "__main__":
    async def _main() -> None:
        logging.basicConfig(level=logging.INFO)
        try:
            print(await get_backend_url())
        except BackendUnavailableError as exc:
            print(str(exc))

    asyncio.run(_main())
