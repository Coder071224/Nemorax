from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from nemorax.backend.core.settings import LLMSettings
from nemorax.backend.core.errors import ConfigurationError
from nemorax.backend.llm.factory import build_provider
from nemorax.backend.llm.providers.openai_compatible import OpenAICompatibleChatProvider


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
