"""OpenAI-compatible chat provider implementation."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
import re
from typing import Any

import httpx

from nemorax.backend.core.errors import ConfigurationError, LLMConnectionError, LLMResponseError
from nemorax.backend.core.logging import get_logger
from nemorax.backend.core.settings import LLMSettings
from nemorax.backend.llm.base import ChatProvider
from nemorax.backend.llm.models import ChatCompletionResult, LLMMessage, ProviderStatus


logger = get_logger("nemorax.llm.openai_compatible")


def _response_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text.strip() or f"HTTP {response.status_code}"

    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()
        detail = payload.get("detail")
        if isinstance(detail, str) and detail.strip():
            return detail.strip()
    return response.text.strip() or f"HTTP {response.status_code}"


def _extract_content(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""

    choices = payload.get("choices", [])
    if not isinstance(choices, list) or not choices:
        return ""

    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        return ""

    message = first_choice.get("message", {})
    if not isinstance(message, dict):
        return ""

    content = message.get("content", "")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
        return "\n".join(parts).strip()
    return ""


def _parse_json_body(response: httpx.Response, provider_label: str) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError as exc:
        detail = response.text.strip() or f"HTTP {response.status_code} with an empty response body."
        raise LLMResponseError(f"{provider_label} returned an invalid response: {detail}") from exc

    if not isinstance(body, dict):
        raise LLMResponseError(f"{provider_label} returned an invalid response payload.")
    return body


def _duration_seconds(raw: str | None) -> int | None:
    if not raw:
        return None

    cleaned = raw.strip().lower()
    if not cleaned:
        return None

    try:
        return max(1, int(float(cleaned)))
    except ValueError:
        pass

    total = 0.0
    matched = False
    for value, unit in re.findall(r"(\d+(?:\.\d+)?)(ms|s|m|h|d)", cleaned):
        matched = True
        amount = float(value)
        if unit == "ms":
            total += amount / 1000.0
        elif unit == "s":
            total += amount
        elif unit == "m":
            total += amount * 60.0
        elif unit == "h":
            total += amount * 3600.0
        elif unit == "d":
            total += amount * 86400.0

    if not matched:
        return None
    return max(1, int(total))


def _format_wait(seconds: int | None) -> str:
    if seconds is None:
        return "later"
    if seconds < 60:
        return f"in about {seconds} seconds"

    delta = timedelta(seconds=seconds)
    total_seconds = int(delta.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    parts: list[str] = []
    if hours:
        parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    if minutes:
        parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
    if not parts:
        parts.append("1 minute")
    return f"in about {' '.join(parts[:2])}"


@dataclass(frozen=True, slots=True)
class _RateLimitInfo:
    kind: str
    retry_after_seconds: int | None


def _rate_limit_info(response: httpx.Response, detail: str) -> _RateLimitInfo:
    lower_detail = detail.lower()
    retry_after_seconds = (
        _duration_seconds(response.headers.get("retry-after"))
        or _duration_seconds(response.headers.get("x-ratelimit-reset-tokens"))
        or _duration_seconds(response.headers.get("x-ratelimit-reset-requests"))
    )

    if any(token in lower_detail for token in ("per day", "(tpd)", "(rpd)", "daily")):
        return _RateLimitInfo(kind="daily", retry_after_seconds=retry_after_seconds)
    if any(token in lower_detail for token in ("per minute", "(tpm)", "(rpm)", "retry after")):
        return _RateLimitInfo(kind="temporary", retry_after_seconds=retry_after_seconds)
    if retry_after_seconds is not None and retry_after_seconds <= 3600:
        return _RateLimitInfo(kind="temporary", retry_after_seconds=retry_after_seconds)
    if retry_after_seconds is not None and retry_after_seconds > 3600:
        return _RateLimitInfo(kind="daily", retry_after_seconds=retry_after_seconds)
    return _RateLimitInfo(kind="unknown", retry_after_seconds=None)


def _friendly_rate_limit_message(info: _RateLimitInfo) -> str:
    prefix = (
        "Sorry for the inconvenience. Nemorax is a free app that helps users navigate "
        "and ask questions about the school. "
    )
    if info.kind == "temporary":
        return (
            prefix
            + f"We've hit a temporary shared usage limit. Please wait {_format_wait(info.retry_after_seconds)} "
            + "and send your question again."
        )
    if info.kind == "daily":
        return (
            prefix
            + f"We've reached today's shared usage limit. Please try again {_format_wait(info.retry_after_seconds)}. "
            + "Thank you for your patience."
        )
    return (
        prefix
        + "The AI service is temporarily unavailable right now. Please try again in a little while."
    )


class OpenAICompatibleChatProvider(ChatProvider):
    def __init__(self, settings: LLMSettings, *, provider_name: str) -> None:
        self._settings = settings
        self._provider_name = provider_name

    @property
    def name(self) -> str:
        return self._provider_name

    @property
    def provider_label(self) -> str:
        labels = {
            "groq": "Groq",
            "openai_compatible": "OpenAI-compatible",
        }
        return labels.get(self._provider_name, self._settings.provider_label)

    @property
    def model(self) -> str:
        return self._settings.model

    @property
    def base_url(self) -> str:
        return self._settings.base_url

    @property
    def fallback_model(self) -> str | None:
        fallback = self._settings.fallback_model
        if not fallback or fallback == self.model:
            return None
        return fallback

    @property
    def _timeout(self) -> httpx.Timeout:
        return httpx.Timeout(
            connect=min(self._settings.health_timeout_seconds, self._settings.request_timeout_seconds),
            read=self._settings.request_timeout_seconds,
            write=30.0,
            pool=5.0,
        )

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._settings.api_key:
            headers["Authorization"] = f"Bearer {self._settings.api_key}"
        return headers

    def _validate_configuration(self) -> None:
        if not self.base_url:
            raise ConfigurationError(f"{self.provider_label} base URL is not configured.")
        if not self.model:
            raise ConfigurationError(f"{self.provider_label} model is not configured.")
        if not self._settings.api_key:
            raise ConfigurationError(f"{self.provider_label} API key is not configured.")

    async def _post_chat_completion(
        self,
        client: httpx.AsyncClient,
        *,
        model: str,
        messages: Sequence[LLMMessage],
        include_reasoning_options: bool = True,
    ) -> ChatCompletionResult:
        payload = {
            "model": model,
            "messages": [{"role": item.role, "content": item.content} for item in messages],
            "temperature": self._settings.temperature,
            "top_p": self._settings.top_p,
            # The frontend expects a single completed reply payload, not SSE chunks.
            "stream": False,
        }
        if self.name == "groq":
            payload["max_completion_tokens"] = self._settings.max_completion_tokens
            if include_reasoning_options:
                payload["reasoning_effort"] = self._settings.reasoning_effort
                payload["include_reasoning"] = self._settings.include_reasoning
            if self._settings.seed is not None:
                payload["seed"] = self._settings.seed
        response = await client.post("/chat/completions", headers=self._headers(), json=payload)
        response.raise_for_status()
        body = _parse_json_body(response, self.provider_label)
        content = _extract_content(body)
        if not content:
            raise LLMResponseError(f"{self.provider_label} returned an empty response.")
        return ChatCompletionResult(
            provider=self.name,
            model=model,
            content=content,
            raw=body,
        )

    def _raise_http_error(self, response: httpx.Response) -> None:
        detail = _response_detail(response)
        if response.status_code == 429:
            raise LLMResponseError(_friendly_rate_limit_message(_rate_limit_info(response, detail)))
        raise LLMResponseError(f"{self.provider_label} request failed: {detail}")

    async def _chat_with_model(
        self,
        client: httpx.AsyncClient,
        *,
        model: str,
        messages: Sequence[LLMMessage],
    ) -> ChatCompletionResult:
        try:
            return await self._post_chat_completion(client, model=model, messages=messages)
        except httpx.HTTPStatusError as exc:
            detail = _response_detail(exc.response).lower()
            if exc.response.status_code == 400 and "reasoning_effort" in detail:
                logger.debug("Retrying %s without reasoning options for model %s", self.provider_label, model)
                return await self._post_chat_completion(
                    client,
                    model=model,
                    messages=messages,
                    include_reasoning_options=False,
                )
            raise

    async def chat(self, messages: Sequence[LLMMessage]) -> ChatCompletionResult:
        self._validate_configuration()
        try:
            async with httpx.AsyncClient(base_url=self.base_url.rstrip("/"), timeout=self._timeout) as client:
                try:
                    return await self._chat_with_model(client, model=self.model, messages=messages)
                except httpx.HTTPStatusError as exc:
                    detail = _response_detail(exc.response)
                    if exc.response.status_code == 429 and self.name == "groq" and self.fallback_model:
                        logger.debug(
                            "Primary Groq model rate-limited; falling back from %s to %s",
                            self.model,
                            self.fallback_model,
                        )
                        try:
                            return await self._chat_with_model(
                                client,
                                model=self.fallback_model,
                                messages=messages,
                            )
                        except httpx.HTTPStatusError as fallback_exc:
                            self._raise_http_error(fallback_exc.response)
                    if exc.response.status_code == 429:
                        raise LLMResponseError(
                            _friendly_rate_limit_message(_rate_limit_info(exc.response, detail))
                        ) from exc
                    raise LLMResponseError(f"{self.provider_label} request failed: {detail}") from exc
        except httpx.HTTPStatusError as exc:
            self._raise_http_error(exc.response)
        except httpx.RequestError as exc:
            raise LLMConnectionError(
                f"{self.provider_label} is not reachable at {self.base_url}."
            ) from exc

    async def health(self) -> ProviderStatus:
        configured = bool(self.base_url and self.model and self._settings.api_key)
        if not configured:
            return ProviderStatus(
                name=self.name,
                label=self.provider_label,
                model=self.model,
                base_url=self.base_url,
                available=False,
                configured=False,
                detail=f"{self.provider_label} configuration is incomplete.",
            )

        try:
            async with httpx.AsyncClient(base_url=self.base_url.rstrip("/"), timeout=self._timeout) as client:
                response = await client.get("/models", headers=self._headers())
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            return ProviderStatus(
                name=self.name,
                label=self.provider_label,
                model=self.model,
                base_url=self.base_url,
                available=False,
                detail=_response_detail(exc.response),
            )
        except httpx.RequestError as exc:
            return ProviderStatus(
                name=self.name,
                label=self.provider_label,
                model=self.model,
                base_url=self.base_url,
                available=False,
                detail=str(exc),
            )

        return ProviderStatus(
            name=self.name,
            label=self.provider_label,
            model=self.model,
            base_url=self.base_url,
            available=True,
        )
