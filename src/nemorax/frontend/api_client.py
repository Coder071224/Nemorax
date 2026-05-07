"""Typed HTTP helpers for the Nemorax frontend."""

from __future__ import annotations

import threading
from typing import Any, Callable
import logging

import httpx

from nemorax.frontend.config import get_api_base_urls, normalize_user_settings


logger = logging.getLogger("nemorax.frontend.api_client")

JsonDict = dict[str, Any]
JsonValue = JsonDict | list[Any]
_TIMEOUT = httpx.Timeout(connect=5.0, read=180.0, write=30.0, pool=5.0)
BACKEND_UNAVAILABLE_MESSAGE = (
    "Unable to reach the Nemis server right now. Please wait a few minutes, then log in to Nemis again."
)
MODEL_NOT_READY_MESSAGE = (
    "Nemis is online, but the AI model is still getting ready. Please wait a few minutes and try again."
)
GENERIC_ERROR_MESSAGE = "Something went wrong. Please try again in a few minutes."


class ApiClientError(Exception):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        code: str | None = None,
        details: Any | None = None,
        kind: str = "unexpected",
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.details = details
        self.kind = kind


def _sanitize_reply_text(text: str) -> str:
    cleaned = (text or "").replace("**", "").replace("*", "")
    cleaned = cleaned.replace("RETRIEVED KNOWLEDGE CONTEXT:", "")
    cleaned = cleaned.replace("Retrieved knowledge context for this reply. Use it as the primary factual reference.", "")
    return cleaned.strip()


def _client(api_base_url: str) -> httpx.Client:
    return httpx.Client(base_url=api_base_url.rstrip("/"), timeout=_TIMEOUT)


def _should_try_next_backend(exc: httpx.HTTPStatusError) -> bool:
    return exc.response.status_code in {502, 503, 504}


def _safe_message_for_error(*, status_code: int | None = None, code: str | None = None) -> tuple[str, str]:
    if status_code == 401 or code == "auth_error":
        return "auth_error", "Incorrect email or password. Please try again."
    if status_code == 404 or code == "not_found":
        return "not_found", "No matching account was found."
    if status_code == 409 or code == "conflict_error":
        return "conflict_error", "That account or item already exists."
    if status_code == 422 or code == "validation_error":
        return "validation_error", "Please check your information and try again."
    if status_code == 429 or code == "rate_limit_error":
        return "rate_limit_error", "Nemis is busy right now. Please wait a few minutes and try again."
    if status_code in {502, 503, 504}:
        if code == "upstream_error":
            return "model_not_ready", MODEL_NOT_READY_MESSAGE
        return "backend_unavailable", BACKEND_UNAVAILABLE_MESSAGE
    if code in {"temporary_failure", "upstream_error"}:
        return "model_not_ready", MODEL_NOT_READY_MESSAGE
    return "unexpected", GENERIC_ERROR_MESSAGE


def _request_once(
    api_base_url: str,
    method: str,
    path: str,
    *,
    payload: JsonDict | None = None,
    params: dict[str, Any] | None = None,
) -> JsonValue:
    with _client(api_base_url) as client:
        response = client.request(method, path, json=payload, params=params)
        response.raise_for_status()
        return _unwrap_api_payload(response.json(), path=path)


def _request(
    method: str,
    path: str,
    *,
    payload: JsonDict | None = None,
    params: dict[str, Any] | None = None,
) -> JsonValue:
    api_base_urls = get_api_base_urls()
    if not api_base_urls:
        logger.warning("No frontend backend API URL is configured.")
        raise ApiClientError(BACKEND_UNAVAILABLE_MESSAGE, kind="backend_unavailable")

    last_request_error: httpx.RequestError | None = None
    for index, api_base_url in enumerate(api_base_urls):
        is_last_backend = index == len(api_base_urls) - 1
        try:
            return _request_once(api_base_url, method, path, payload=payload, params=params)
        except httpx.HTTPStatusError as exc:
            if not is_last_backend and _should_try_next_backend(exc):
                continue
            default_message = f"Backend error {exc.response.status_code}."
            _, code, details = _read_http_error_payload(exc.response, default_message)
            logger.warning(
                "Backend request failed | method=%s path=%s status=%s code=%s",
                method,
                path,
                exc.response.status_code,
                code,
            )
            kind, safe_message = _safe_message_for_error(status_code=exc.response.status_code, code=code)
            raise ApiClientError(
                safe_message,
                status_code=exc.response.status_code,
                code=code,
                details=details,
                kind=kind,
            ) from exc
        except httpx.RequestError as exc:
            logger.warning("Backend request unreachable | method=%s path=%s", method, path)
            last_request_error = exc
            if not is_last_backend:
                continue
            raise ApiClientError(
                BACKEND_UNAVAILABLE_MESSAGE,
                kind="backend_unavailable",
            ) from exc
        except ValueError as exc:
            logger.warning("Invalid backend response | method=%s path=%s", method, path)
            raise ApiClientError(GENERIC_ERROR_MESSAGE, kind="unexpected") from exc

    raise ApiClientError(
        BACKEND_UNAVAILABLE_MESSAGE,
        kind="backend_unavailable",
    ) from last_request_error


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
        logger.warning("Invalid backend response envelope | path=%s payload_type=%s", path, type(payload).__name__)
        raise ApiClientError(GENERIC_ERROR_MESSAGE, kind="unexpected")
    ok = payload.get("ok")
    if ok is not True:
        error = payload.get("error")
        if isinstance(error, dict):
            message = str(error.get("message") or "").strip() or "Request failed."
            code = str(error.get("code") or "").strip() or None
            logger.warning("Backend returned error envelope with HTTP 200 | path=%s code=%s detail=%r", path, code, message)
            kind, safe_message = _safe_message_for_error(code=code)
            raise ApiClientError(safe_message, code=code, details=error.get("details"), kind=kind)
        logger.warning("Invalid backend response envelope | path=%s payload=%r", path, payload)
        raise ApiClientError(GENERIC_ERROR_MESSAGE, kind="unexpected")
    return payload.get("data")


def _post(path: str, payload: JsonDict) -> JsonDict:
    result = _request("POST", path, payload=payload)
    if not isinstance(result, dict):
        logger.warning("Invalid POST response type | path=%s result_type=%s", path, type(result).__name__)
        raise ApiClientError(GENERIC_ERROR_MESSAGE, kind="unexpected")
    return result


def _get(path: str, *, params: dict[str, Any] | None = None) -> JsonValue:
    return _request("GET", path, params=params)


def _delete(path: str, *, params: dict[str, Any] | None = None) -> None:
    _request("DELETE", path, params=params)


def check_health() -> JsonDict:
    result = _get("/api/health")
    if not isinstance(result, dict):
        logger.warning("Invalid backend health response type | result_type=%s", type(result).__name__)
        raise ApiClientError(GENERIC_ERROR_MESSAGE, kind="unexpected")
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
            logger.exception("Unexpected frontend error while sending chat message", exc_info=exc)
            on_error(GENERIC_ERROR_MESSAGE)

    threading.Thread(target=_worker, daemon=True).start()


def list_history(user_id: str) -> list[JsonDict]:
    result = _get("/api/history", params={"user_id": user_id})
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

