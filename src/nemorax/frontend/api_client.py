"""Typed HTTP helpers for the Nemorax frontend."""

from __future__ import annotations

import threading
from typing import Any, Callable

import httpx

from nemorax.frontend.config import get_api_base_url, normalize_user_settings


JsonDict = dict[str, Any]
JsonValue = JsonDict | list[Any]
_TIMEOUT = httpx.Timeout(connect=5.0, read=180.0, write=30.0, pool=5.0)


class ApiClientError(Exception):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        code: str | None = None,
        details: Any | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.details = details


def _sanitize_reply_text(text: str) -> str:
    cleaned = (text or "").replace("**", "").replace("*", "")
    cleaned = cleaned.replace("RETRIEVED KNOWLEDGE CONTEXT:", "")
    cleaned = cleaned.replace("Retrieved knowledge context for this reply. Use it as the primary factual reference.", "")
    return cleaned.strip()


def _client() -> httpx.Client:
    api_base_url = get_api_base_url()
    if not api_base_url:
        raise ApiClientError("Backend API URL is not configured. Set NEMORAX_API_URL for this frontend runtime.")
    return httpx.Client(base_url=api_base_url.rstrip("/"), timeout=_TIMEOUT)


def _friendly_error_message(
    *,
    status_code: int | None,
    message: str,
    code: str | None = None,
) -> str:
    if status_code in {500, 502, 503}:
        return "The service is temporarily unavailable. Please try again."
    if status_code == 401:
        return message or "Authentication failed."
    if status_code == 403:
        return message or "You do not have permission to do that."
    if status_code == 404:
        return message or "The requested item was not found."
    if status_code == 422:
        return message or "The request is invalid."
    if status_code == 429 or code == "rate_limit_error":
        return message or "Too many requests right now. Please try again shortly."
    return message or f"Backend error {status_code}."


def _read_http_error_payload(response: httpx.Response, default_message: str) -> tuple[str, str | None, Any | None]:
    try:
        payload = response.json()
    except ValueError:
        return default_message, None, None

    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            code = error.get("code")
            details = error.get("details")
            if isinstance(message, str) and message.strip():
                return message.strip(), str(code).strip() or None, details
        detail = payload.get("detail")
        if isinstance(detail, str) and detail.strip():
            return detail.strip(), None, None
    return default_message, None, None


def _unwrap_api_payload(payload: JsonValue, *, path: str) -> JsonValue:
    if not isinstance(payload, dict):
        raise ApiClientError(f"Invalid backend response for {path}: expected a JSON object envelope.")
    ok = payload.get("ok")
    if ok is not True:
        error = payload.get("error")
        if isinstance(error, dict):
            message = str(error.get("message") or "").strip() or "Request failed."
            code = str(error.get("code") or "").strip() or None
            raise ApiClientError(message, code=code, details=error.get("details"))
        raise ApiClientError(f"Invalid backend response for {path}: missing success envelope.")
    return payload.get("data")


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
            return _unwrap_api_payload(response.json(), path=path)
    except httpx.HTTPStatusError as exc:
        default_message = f"Backend error {exc.response.status_code}."
        message, code, details = _read_http_error_payload(exc.response, default_message)
        raise ApiClientError(
            _friendly_error_message(status_code=exc.response.status_code, message=message, code=code),
            status_code=exc.response.status_code,
            code=code,
            details=details,
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
    display_name = result.get("display_name")
    return {
        "user_id": str(result.get("user_id", "") or ""),
        "email": str(result.get("email", "") or ""),
        "display_name": display_name.strip() if isinstance(display_name, str) and display_name.strip() else None,
        "settings": normalize_user_settings(result),
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
            if isinstance(reply, str) and reply:
                on_response(_sanitize_reply_text(reply) or "No reply received.")
            else:
                on_response("No reply received.")
        except ApiClientError as exc:
            on_error(str(exc))
        except Exception as exc:  # pragma: no cover - defensive fallback
            on_error(f"Unexpected error while sending the message: {exc}")

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
        result = _request("DELETE", f"/api/history/{session_id}", params={"user_id": user_id})
    except ApiClientError:
        return False
    return isinstance(result, dict) and str(result.get("session_id", "")).strip() == session_id


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
    if not isinstance(result, dict):
        return {}
    return normalize_user_settings(result.get("settings"))


def save_user_settings(user_id: str, settings: JsonDict) -> bool:
    try:
        result = _post(f"/api/settings/{user_id}", settings)
    except ApiClientError:
        return False
    return isinstance(result.get("settings"), dict)


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

