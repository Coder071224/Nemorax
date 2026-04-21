from __future__ import annotations

from dataclasses import replace
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from nemorax.backend.api.app import create_app
from nemorax.backend.core.settings import ApiSettings
from tests.test_backend_app import FakeSupabaseTransport, StubProvider, build_test_services, build_test_settings


class BackendCorsTests(unittest.TestCase):
    def test_api_settings_normalize_and_dedupe_origins(self) -> None:
        settings = ApiSettings(
            app_name="Nemorax API",
            app_version="1.0.0",
            environment="production",
            log_level="INFO",
            backend_host="0.0.0.0",
            backend_port=8000,
            backend_url="https://api.example.com",
            cors_origins_raw="https://web.example.com/, https://web.example.com, *, http://localhost:8550/",
        )

        self.assertEqual(
            settings.cors_origins,
            ["https://web.example.com", "http://localhost:8550"],
        )
        self.assertFalse(settings.cors_allow_credentials)

    def test_allowed_origin_receives_preflight_headers(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            settings = build_test_settings(Path(tempdir))
            settings = replace(
                settings,
                api=replace(settings.api, cors_origins_raw="http://127.0.0.1:8550"),
            )
            services = build_test_services(settings, StubProvider(), FakeSupabaseTransport())
            client = TestClient(create_app(services=services))

            response = client.options(
                "/api/health",
                headers={
                    "Origin": "http://127.0.0.1:8550",
                    "Access-Control-Request-Method": "GET",
                },
            )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers.get("access-control-allow-origin"), "http://127.0.0.1:8550")

    def test_disallowed_origin_does_not_receive_cors_headers(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            settings = build_test_settings(Path(tempdir))
            settings = replace(
                settings,
                api=replace(settings.api, cors_origins_raw="https://web.example.com"),
            )
            services = build_test_services(settings, StubProvider(), FakeSupabaseTransport())
            client = TestClient(create_app(services=services))

            response = client.get("/api/health", headers={"Origin": "https://evil.example.com"})

            self.assertEqual(response.status_code, 200)
            self.assertIsNone(response.headers.get("access-control-allow-origin"))


if __name__ == "__main__":
    unittest.main()
