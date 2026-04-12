"""Utility to migrate legacy storage into the active Nemorax layout."""
from __future__ import annotations

from nemorax.backend.config import DATA_DIR, HISTORY_DIR, USERS_DIR
from nemorax.backend.repositories.json_store import read_json_object, write_json_atomic


def migrate() -> None:
    legacy_users_root = DATA_DIR / "users"
    if not legacy_users_root.exists():
        return

    for user_dir in legacy_users_root.iterdir():
        if not user_dir.is_dir():
            continue
        user_id = user_dir.name
        profile_path = user_dir / "profile.json"
        settings_path = user_dir / "settings.json"
        history_dir = user_dir / "history"

        if profile_path.exists():
            profile = read_json_object(profile_path) or {}
            if isinstance(profile, dict):
                target = USERS_DIR / f"{user_id}.json"
                existing = read_json_object(target) or {}
                merged = {**existing, **profile}
                if settings_path.exists():
                    settings = read_json_object(settings_path) or {}
                    if isinstance(settings, dict):
                        merged["settings"] = settings
                write_json_atomic(target, merged)

        if history_dir.exists():
            target_history = HISTORY_DIR / f"{user_id}.json"
            conversations: list[dict] = []
            for session_file in history_dir.glob("*.json"):
                session = read_json_object(session_file)
                if isinstance(session, dict):
                    conversations.append(session)
            payload = {"user_id": user_id, "conversations": conversations}
            write_json_atomic(target_history, payload)


if __name__ == "__main__":
    migrate()
