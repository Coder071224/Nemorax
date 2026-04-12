from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from nemorax.backend.core.errors import LLMResponseError
from nemorax.backend.core.settings import LLMSettings
from nemorax.backend.llm.models import LLMMessage
from nemorax.backend.llm.providers.openai_compatible import OpenAICompatibleChatProvider


def _build_response(
    *,
    status_code: int,
    payload: dict[str, object],
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    return httpx.Response(status_code=status_code, json=payload, headers=headers, request=request)


class _FakeAsyncClient:
    def __init__(self, responses: list[httpx.Response]) -> None:
        self._responses = list(responses)
        self.models_used: list[str] = []

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, _exc_type, _exc, _tb) -> None:
        return None

    async def post(self, path: str, *, headers: dict[str, str] | None = None, json: dict[str, object]) -> httpx.Response:
        del path, headers
        self.models_used.append(str(json.get("model", "")))
        return self._responses.pop(0)

    async def get(self, path: str, *, headers: dict[str, str] | None = None) -> httpx.Response:
        del path, headers
        return _build_response(status_code=200, payload={"data": []})


class GroqRateLimitTests(unittest.TestCase):
    @staticmethod
    def _settings() -> LLMSettings:
        return LLMSettings(
            provider="groq",
            model="openai/gpt-oss-120b",
            fallback_model="llama-3.1-8b-instant",
            base_url="https://api.groq.com/openai/v1",
            api_key="secret",
            request_timeout_seconds=30.0,
            health_timeout_seconds=5.0,
            temperature=0.4,
            top_p=0.9,
            max_context_tokens=4096,
            message_window=10,
            prompt_knowledge_chars=6000,
        )

    def test_falls_back_to_secondary_model_on_temporary_rate_limit(self) -> None:
        fake_client = _FakeAsyncClient(
            [
                _build_response(
                    status_code=429,
                    payload={
                        "error": {
                            "message": "Rate limit reached on tokens per minute (TPM).",
                        }
                    },
                    headers={"retry-after": "8"},
                ),
                _build_response(
                    status_code=200,
                    payload={
                        "choices": [
                            {
                                "message": {
                                    "content": "Fallback answer",
                                }
                            }
                        ]
                    },
                ),
            ]
        )
        provider = OpenAICompatibleChatProvider(self._settings(), provider_name="groq")

        with patch("nemorax.backend.llm.providers.openai_compatible.httpx.AsyncClient", return_value=fake_client):
            result = asyncio.run(
                provider.chat([LLMMessage(role="user", content="Where is the registrar?")])
            )

        self.assertEqual(result.model, "llama-3.1-8b-instant")
        self.assertEqual(result.content, "Fallback answer")
        self.assertEqual(fake_client.models_used, ["openai/gpt-oss-120b", "llama-3.1-8b-instant"])

    def test_returns_polite_daily_limit_message_when_fallback_is_also_limited(self) -> None:
        fake_client = _FakeAsyncClient(
            [
                _build_response(
                    status_code=429,
                    payload={"error": {"message": "Rate limit reached on tokens per minute (TPM)."}},
                    headers={"retry-after": "6"},
                ),
                _build_response(
                    status_code=429,
                    payload={"error": {"message": "Rate limit reached on tokens per day (TPD)."}},
                    headers={"x-ratelimit-reset-requests": "1d"},
                ),
            ]
        )
        provider = OpenAICompatibleChatProvider(self._settings(), provider_name="groq")

        with patch("nemorax.backend.llm.providers.openai_compatible.httpx.AsyncClient", return_value=fake_client):
            with self.assertRaisesRegex(LLMResponseError, "Sorry for the inconvenience"):
                asyncio.run(
                    provider.chat([LLMMessage(role="user", content="Where is the registrar?")])
                )


if __name__ == "__main__":
    unittest.main()
