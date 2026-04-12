from __future__ import annotations

import sys
import unittest
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from nemorax.backend.core.settings import LLMSettings
from nemorax.backend.core.errors import ConfigurationError, LLMResponseError
from nemorax.backend.llm.factory import build_provider
from nemorax.backend.llm.providers.openai_compatible import OpenAICompatibleChatProvider
from nemorax.backend.llm.models import LLMMessage


class ProviderFactoryTests(unittest.TestCase):
    def test_builds_groq_provider_through_openai_compatible_adapter(self) -> None:
        provider = build_provider(
            LLMSettings(
                provider="groq",
                model="llama-test",
                fallback_model="llama-fallback",
                base_url="https://api.groq.com/openai/v1",
                api_key="secret",
                request_timeout_seconds=30.0,
                health_timeout_seconds=5.0,
                temperature=0.25,
                top_p=1.0,
                max_completion_tokens=900,
                reasoning_effort="medium",
                include_reasoning=False,
                stream=True,
                seed=7,
                max_context_tokens=4096,
                message_window=10,
                prompt_knowledge_chars=6000,
            )
        )
        self.assertIsInstance(provider, OpenAICompatibleChatProvider)
        self.assertEqual(provider.name, "groq")

    def test_rejects_unsupported_provider(self) -> None:
        with self.assertRaisesRegex(ConfigurationError, "Unsupported LLM_PROVIDER value"):
            build_provider(
                LLMSettings(
                    provider="local_model",
                    model="test-model",
                    fallback_model=None,
                    base_url="http://127.0.0.1:9999",
                    api_key=None,
                    request_timeout_seconds=30.0,
                    health_timeout_seconds=5.0,
                    temperature=0.25,
                    top_p=1.0,
                    max_completion_tokens=900,
                    reasoning_effort="medium",
                    include_reasoning=False,
                    stream=True,
                    seed=7,
                    max_context_tokens=4096,
                    message_window=10,
                    prompt_knowledge_chars=6000,
                )
            )

    def test_invalid_json_provider_response_raises_clean_error(self) -> None:
        provider = OpenAICompatibleChatProvider(
            LLMSettings(
                provider="groq",
                model="llama-test",
                fallback_model=None,
                base_url="https://api.groq.com/openai/v1",
                api_key="secret",
                request_timeout_seconds=30.0,
                health_timeout_seconds=5.0,
                temperature=0.25,
                top_p=1.0,
                max_completion_tokens=900,
                reasoning_effort="medium",
                include_reasoning=False,
                stream=True,
                seed=7,
                max_context_tokens=4096,
                message_window=10,
                prompt_knowledge_chars=6000,
            ),
            provider_name="groq",
        )

        response = httpx.Response(
            200,
            content=b"",
            request=httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions"),
        )

        class DummyClient:
            async def post(self, *args, **kwargs):
                return response

        async def run_test() -> None:
            with self.assertRaisesRegex(LLMResponseError, "returned an invalid response"):
                await provider._post_chat_completion(
                    DummyClient(),
                    model="llama-test",
                    messages=[LLMMessage(role="user", content="Hello")],
                )

        import asyncio

        asyncio.run(run_test())

    def test_chat_completion_requests_non_streaming_payload(self) -> None:
        provider = OpenAICompatibleChatProvider(
            LLMSettings(
                provider="groq",
                model="llama-test",
                fallback_model=None,
                base_url="https://api.groq.com/openai/v1",
                api_key="secret",
                request_timeout_seconds=30.0,
                health_timeout_seconds=5.0,
                temperature=0.25,
                top_p=1.0,
                max_completion_tokens=900,
                reasoning_effort="medium",
                include_reasoning=False,
                stream=True,
                seed=7,
                max_context_tokens=4096,
                message_window=10,
                prompt_knowledge_chars=6000,
            ),
            provider_name="groq",
        )

        captured_payload: dict[str, object] = {}
        response = httpx.Response(
            200,
            json={"choices": [{"message": {"content": "Hello"}}]},
            request=httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions"),
        )

        class DummyClient:
            async def post(self, *args, **kwargs):
                captured_payload.update(kwargs.get("json", {}))
                return response

        async def run_test() -> None:
            result = await provider._post_chat_completion(
                DummyClient(),
                model="llama-test",
                messages=[LLMMessage(role="user", content="Hello")],
            )
            self.assertEqual(result.content, "Hello")

        import asyncio

        asyncio.run(run_test())
        self.assertIs(captured_payload.get("stream"), False)

    def test_chat_retries_without_reasoning_options_when_model_rejects_them(self) -> None:
        provider = OpenAICompatibleChatProvider(
            LLMSettings(
                provider="groq",
                model="llama-test",
                fallback_model=None,
                base_url="https://api.groq.com/openai/v1",
                api_key="secret",
                request_timeout_seconds=30.0,
                health_timeout_seconds=5.0,
                temperature=0.25,
                top_p=1.0,
                max_completion_tokens=900,
                reasoning_effort="medium",
                include_reasoning=False,
                stream=True,
                seed=7,
                max_context_tokens=4096,
                message_window=10,
                prompt_knowledge_chars=6000,
            ),
            provider_name="groq",
        )

        payloads: list[dict[str, object]] = []
        responses = [
            httpx.Response(
                400,
                json={"error": {"message": "`reasoning_effort` is not supported with this model"}},
                request=httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions"),
            ),
            httpx.Response(
                200,
                json={"choices": [{"message": {"content": "Hello"}}]},
                request=httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions"),
            ),
        ]

        class DummyClient:
            async def post(self, *args, **kwargs):
                payloads.append(dict(kwargs.get("json", {})))
                return responses.pop(0)

        async def run_test() -> None:
            result = await provider._chat_with_model(
                DummyClient(),
                model="llama-test",
                messages=[LLMMessage(role="user", content="Hello")],
            )
            self.assertEqual(result.content, "Hello")

        import asyncio

        asyncio.run(run_test())
        self.assertEqual(len(payloads), 2)
        self.assertIn("reasoning_effort", payloads[0])
        self.assertNotIn("reasoning_effort", payloads[1])
