"""Typed HTTP helpers for the Nemorax frontend."""

from __future__ import annotations

import threading
from typing import Any, Callable

import httpx

from nemorax.frontend.config import BACKEND_URL


JsonDict = dict[str, Any]
JsonValue = JsonDict | list[Any]
_TIMEOUT = httpx.Timeout(connect=5.0, read=180.0, write=30.0, pool=5.0)


class ApiClientError(Exception):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _client() -> httpx.Client:
    return httpx.Client(base_url=BACKEND_URL.rstrip("/"), timeout=_TIMEOUT)


def _read_http_error_detail(response: httpx.Response, default_message: str) -> str:
    try:
        payload = response.json()
    except ValueError:
        return default_message

    if isinstance(payload, dict):
        detail = payload.get("detail")
        if isinstance(detail, str) and detail.strip():
            return detail.strip()
    return default_message


def _request(
    method: str,
    path: str,
    *,
    payload: JsonDict | None = None,
    params: dict[str, Any] | None = None,
) -> JsonValue:
    try:
        with _client() as client:
            response = client.request(method, path, json=payload, params=params)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as exc:
        default_message = f"Backend error {exc.response.status_code}."
        raise ApiClientError(
            _read_http_error_detail(exc.response, default_message),
            status_code=exc.response.status_code,
        ) from exc
    except httpx.RequestError as exc:
        raise ApiClientError(
            "Cannot reach the backend. Make sure the server is running and accessible.",
        ) from exc
    except ValueError as exc:
        raise ApiClientError(f"Invalid backend response: {exc}") from exc


def _post(path: str, payload: JsonDict) -> JsonDict:
    result = _request("POST", path, payload=payload)
    if not isinstance(result, dict):
        raise ApiClientError(f"Expected JSON object response for POST {path!r}.")
    return result


def _get(path: str, *, params: dict[str, Any] | None = None) -> JsonValue:
    return _request("GET", path, params=params)


def _delete(path: str, *, params: dict[str, Any] | None = None) -> None:
    _request("DELETE", path, params=params)


def check_health() -> JsonDict:
    result = _get("/api/health")
    if not isinstance(result, dict):
        raise ApiClientError("Invalid backend health response.")
    return result


def _normalize_public_user(result: JsonDict) -> JsonDict:
    settings = result.get("settings", {})
    display_name = result.get("display_name")
    normalized_settings: JsonDict = {}
    if isinstance(settings, dict):
        theme = settings.get("theme")
        if isinstance(theme, str) and theme.strip():
            normalized_settings["theme"] = theme.strip()
    return {
        "user_id": str(result.get("user_id", "") or ""),
        "email": str(result.get("email", "") or ""),
        "display_name": display_name.strip() if isinstance(display_name, str) and display_name.strip() else None,
        "settings": normalized_settings,
    }


def send_message(
    session_id: str,
    messages: list[dict[str, str]],
    on_response: Callable[[str], None],
    on_error: Callable[[str], None],
    user_id: str | None = None,
) -> None:
    def _worker() -> None:
        try:
            payload: JsonDict = {"session_id": session_id, "messages": messages}
            if user_id:
                payload["user_id"] = user_id
            result = _post("/api/chat", payload)
            reply = result.get("reply")
            on_response(reply if isinstance(reply, str) and reply else "No reply received.")
        except ApiClientError as exc:
            on_error(f"Warning: {exc}")
        except Exception as exc:  # pragma: no cover - defensive fallback
            on_error(f"Unexpected error: {exc}")

    threading.Thread(target=_worker, daemon=True).start()


def list_history(user_id: str) -> list[JsonDict]:
    try:
        result = _get("/api/history", params={"user_id": user_id})
    except ApiClientError:
        return []
    return [item for item in result if isinstance(item, dict)] if isinstance(result, list) else []


def load_conversation(session_id: str, user_id: str) -> JsonDict | None:
    try:
        result = _get(f"/api/history/{session_id}", params={"user_id": user_id})
    except ApiClientError:
        return None
    return result if isinstance(result, dict) else None


def delete_conversation(session_id: str, user_id: str) -> bool:
    try:
        _delete(f"/api/history/{session_id}", params={"user_id": user_id})
    except ApiClientError:
        return False
    return True


def submit_feedback(
    comment: str,
    session_id: str | None = None,
    rating: int | None = None,
    category: str | None = None,
    user_id: str | None = None,
) -> bool:
    payload: JsonDict = {"comment": comment}
    if session_id:
        payload["session_id"] = session_id
    if rating is not None:
        payload["rating"] = rating
    if category:
        payload["category"] = category
    if user_id:
        payload["user_id"] = user_id

    try:
        _post("/api/feedback", payload)
    except ApiClientError:
        return False
    return True


def load_user_settings(user_id: str) -> JsonDict:
    try:
        result = _get(f"/api/settings/{user_id}")
    except ApiClientError:
        return {}
    return result if isinstance(result, dict) else {}


def save_user_settings(user_id: str, settings: JsonDict) -> bool:
    try:
        _post(f"/api/settings/{user_id}", settings)
    except ApiClientError:
        return False
    return True


def load_user_profile(user_id: str) -> JsonDict | None:
    try:
        result = _get(f"/api/users/{user_id}")
    except ApiClientError:
        return None
    return _normalize_public_user(result) if isinstance(result, dict) else None


def save_display_name(user_id: str, display_name: str | None) -> tuple[JsonDict | None, str]:
    try:
        payload: JsonDict = {"display_name": display_name}
        result = _post(f"/api/users/{user_id}/display-name", payload)
        return _normalize_public_user(result), ""
    except ApiClientError as exc:
        if exc.status_code == 404:
            return None, "Unable to find that account."
        return None, str(exc)


def auth_register(email: str, password: str, recovery_answers: dict[str, str]) -> tuple[bool, str]:
    try:
        result = _post(
            "/api/auth/register",
            {"email": email, "password": password, "recovery_answers": recovery_answers},
        )
    except ApiClientError as exc:
        return False, str(exc)
    message = result.get("message")
    return True, message if isinstance(message, str) and message else "Account created."


def auth_login(email: str, password: str) -> tuple[JsonDict | None, str]:
    try:
        result = _post("/api/auth/login", {"email": email, "password": password})
    except ApiClientError as exc:
        return None, str(exc)
    user = _normalize_public_user(result)
    message = result.get("message")
    return user, message if isinstance(message, str) and message else "Login successful."


def auth_get_recovery_questions(email: str) -> tuple[list[str], str]:
    try:
        result = _post("/api/auth/recovery/questions", {"email": email})
    except ApiClientError as exc:
        return [], str(exc)
    questions = result.get("questions", [])
    if isinstance(questions, list):
        return [item for item in questions if isinstance(item, str)], ""
    return [], ""


def auth_verify_recovery(email: str, answers: dict[str, str]) -> tuple[bool, str]:
    try:
        result = _post("/api/auth/recovery/verify", {"email": email, "answers": answers})
    except ApiClientError as exc:
        return False, str(exc)
    message = result.get("message")
    return True, message if isinstance(message, str) and message else "Verified."


def auth_reset_password(email: str, new_password: str) -> tuple[bool, str]:
    try:
        result = _post("/api/auth/recovery/reset", {"email": email, "new_password": new_password})
    except ApiClientError as exc:
        return False, str(exc)
    message = result.get("message")
    return True, message if isinstance(message, str) and message else "Password reset."

