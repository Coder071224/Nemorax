from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from nemorax.frontend import auth_session


def test_finalize_login_auth_session_uses_backend_profile_when_available(monkeypatch) -> None:
    async def _fake_save(page, user):
        return True

    async def _fake_clear(page):
        raise AssertionError("clear should not be called")

    def _fake_load_profile(user_id: str):
        assert user_id == "user-1"
        return {
            "user_id": "user-1",
            "email": "user@example.com",
            "display_name": "Profile User",
            "settings": {"theme": "emerald_noir"},
        }

    monkeypatch.setattr(auth_session, "save_native_auth_session", _fake_save)
    monkeypatch.setattr(auth_session, "clear_auth_session", _fake_clear)
    monkeypatch.setattr(auth_session.api_client, "load_user_profile", _fake_load_profile)

    resolved = asyncio.run(
        auth_session.finalize_login_auth_session(
            object(),
            {
                "user_id": "user-1",
                "email": "user@example.com",
            },
        )
    )

    assert resolved == {
        "user_id": "user-1",
        "email": "user@example.com",
        "display_name": "Profile User",
        "settings": {"theme": "emerald_noir"},
    }


def test_finalize_login_auth_session_falls_back_to_login_payload(monkeypatch) -> None:
    async def _fake_save(page, user):
        return True

    async def _fake_clear(page):
        raise AssertionError("clear should not be called")

    monkeypatch.setattr(auth_session, "save_native_auth_session", _fake_save)
    monkeypatch.setattr(auth_session, "clear_auth_session", _fake_clear)
    monkeypatch.setattr(auth_session.api_client, "load_user_profile", lambda _: None)

    resolved = asyncio.run(
        auth_session.finalize_login_auth_session(
            object(),
            {
                "user_id": "user-1",
                "email": "user@example.com",
                "settings": {"show_splash": False},
            },
        )
    )

    assert resolved == {
        "user_id": "user-1",
        "email": "user@example.com",
        "settings": {"show_splash": False},
    }


def test_refresh_auth_session_clears_invalid_state(monkeypatch) -> None:
    cleared = {"called": False}

    async def _fake_clear(page):
        cleared["called"] = True

    async def _fake_save(page, user):
        raise AssertionError("save should not be called")

    monkeypatch.setattr(auth_session, "clear_auth_session", _fake_clear)
    monkeypatch.setattr(auth_session, "save_native_auth_session", _fake_save)
    monkeypatch.setattr(auth_session.api_client, "load_user_profile", lambda _: None)

    resolved = asyncio.run(
        auth_session.refresh_auth_session(
            object(),
            {
                "user_id": "user-1",
                "email": "user@example.com",
            },
        )
    )

    assert resolved is None
    assert cleared["called"] is True
