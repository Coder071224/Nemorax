from __future__ import annotations

import importlib
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


class FrontendApiConfigTests(unittest.TestCase):
    def _reload_config(self):
        import nemorax.frontend.config as config

        return importlib.reload(config)

    def test_local_development_defaults_to_port_8000(self) -> None:
        with patch.dict(os.environ, {"NEMORAX_ENV": "development"}, clear=True):
            config = self._reload_config()

        self.assertEqual(config.get_api_base_urls(), ["http://127.0.0.1:8000"])

    def test_render_primary_can_have_railway_fallback(self) -> None:
        with patch.dict(
            os.environ,
            {
                "NEMORAX_ENV": "production",
                "NEMORAX_API_URL": "https://nemorax-backend.onrender.com/",
                "NEMORAX_API_FALLBACK_URLS": "https://fallback.example.com, https://nemorax-backend.onrender.com",
            },
            clear=True,
        ):
            config = self._reload_config()

        self.assertEqual(
            config.get_api_base_urls(),
            ["https://nemorax-backend.onrender.com", "https://fallback.example.com"],
        )

    def test_nemis_primary_secondary_envs_drive_cross_host_failover(self) -> None:
        with patch.dict(
            os.environ,
            {
                "NEMORAX_ENV": "production",
                "NEMIS_PRIMARY_BACKEND_URL": "https://render.example.com/",
                "NEMIS_SECONDARY_BACKEND_URL": "https://railway.example.com/",
                "NEMORAX_API_URL": "https://legacy.example.com/",
            },
            clear=True,
        ):
            config = self._reload_config()

        self.assertEqual(
            config.get_api_base_urls(),
            ["https://render.example.com", "https://railway.example.com"],
        )

    def test_backend_urls_without_scheme_default_to_https(self) -> None:
        with patch.dict(
            os.environ,
            {
                "NEMORAX_ENV": "production",
                "NEMIS_PRIMARY_BACKEND_URL": "render.example.com",
                "NEMIS_SECONDARY_BACKEND_URL": "railway.example.com",
            },
            clear=True,
        ):
            config = self._reload_config()

        self.assertEqual(
            config.get_api_base_urls(),
            ["https://render.example.com", "https://railway.example.com"],
        )

    def test_production_without_env_uses_public_cross_host_defaults(self) -> None:
        with patch.dict(os.environ, {"NEMORAX_ENV": "production"}, clear=True):
            config = self._reload_config()

        self.assertEqual(
            config.get_api_base_urls(),
            [
                "https://nemorax-backend-c1ma.onrender.com",
                "https://nemoraxbackend-production.up.railway.app",
            ],
        )

    def test_api_client_tries_fallback_after_temporary_backend_error(self) -> None:
        from nemorax.frontend import api_client

        def _client(base_url: str) -> httpx.Client:
            def _handler(request: httpx.Request) -> httpx.Response:
                if "primary.example.com" in str(request.url):
                    return httpx.Response(status_code=503, json={"detail": "starting"}, request=request)
                return httpx.Response(status_code=200, json={"ok": True, "data": {"available": True}}, request=request)

            return httpx.Client(base_url=base_url, transport=httpx.MockTransport(_handler))

        with patch.object(
            api_client,
            "get_api_base_urls",
            return_value=["https://primary.example.com", "https://fallback.example.com"],
        ), patch.object(api_client, "_client", side_effect=_client):
            result = api_client.check_health()

        self.assertEqual(result, {"available": True})

    def test_api_client_hides_backend_unreachable_details(self) -> None:
        from nemorax.frontend import api_client

        def _client(base_url: str) -> httpx.Client:
            def _handler(request: httpx.Request) -> httpx.Response:
                raise httpx.ConnectError("getaddrinfo failed for internal.host.local", request=request)

            return httpx.Client(base_url=base_url, transport=httpx.MockTransport(_handler))

        with patch.object(api_client, "get_api_base_urls", return_value=["https://primary.example.com"]), patch.object(
            api_client,
            "_client",
            side_effect=_client,
        ):
            with self.assertRaises(api_client.ApiClientError) as caught:
                api_client.check_health()

        self.assertEqual(str(caught.exception), api_client.BACKEND_UNAVAILABLE_MESSAGE)
        self.assertNotIn("internal.host.local", str(caught.exception))

    def test_api_client_maps_model_provider_failure_to_model_not_ready(self) -> None:
        from nemorax.frontend import api_client

        def _client(base_url: str) -> httpx.Client:
            def _handler(request: httpx.Request) -> httpx.Response:
                return httpx.Response(
                    status_code=502,
                    json={
                        "ok": False,
                        "error": {
                            "code": "upstream_error",
                            "message": "Groq request failed: token provider stack trace",
                        },
                    },
                    request=request,
                )

            return httpx.Client(base_url=base_url, transport=httpx.MockTransport(_handler))

        with patch.object(api_client, "get_api_base_urls", return_value=["https://primary.example.com"]), patch.object(
            api_client,
            "_client",
            side_effect=_client,
        ):
            with self.assertRaises(api_client.ApiClientError) as caught:
                api_client.check_health()

        self.assertEqual(str(caught.exception), api_client.MODEL_NOT_READY_MESSAGE)
        self.assertNotIn("Groq", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
