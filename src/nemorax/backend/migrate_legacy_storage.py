"""Explicit importer for legacy JSON-backed app data into Supabase."""

from __future__ import annotations

import argparse
from collections.abc import Iterable
from pathlib import Path
from typing import Any
import uuid

from nemorax.backend.config import DATA_DIR
from nemorax.backend.core.logging import get_logger
from nemorax.backend.core.settings import settings
from nemorax.backend.repositories import FeedbackRepository, HistoryRepository, SupabasePersistenceClient, UserRepository
from nemorax.backend.repositories.json_store import read_json_object
logger = get_logger("nemorax.legacy_import")

_LEGACY_USER_NAMESPACE = uuid.UUID("f4a8b2ee-7d3b-4d39-8df6-4fcb7a8d6c31")


def canonical_user_id(raw_user_id: str) -> str:
    cleaned = raw_user_id.strip()
    if not cleaned:
        return ""
    try:
        return str(uuid.UUID(cleaned))
    except ValueError:
        return str(uuid.uuid5(_LEGACY_USER_NAMESPACE, cleaned.lower()))


def _iter_json_files(directory: Path) -> Iterable[Path]:
    if not directory.exists():
        return []
    return sorted(path for path in directory.glob("*.json") if path.is_file())


def _legacy_users(root: Path) -> list[dict[str, Any]]:
    users: dict[str, dict[str, Any]] = {}

    for path in _iter_json_files(root / "USERS"):
        payload = read_json_object(path)
        if isinstance(payload, dict):
            user_id = str(payload.get("user_id", path.stem)).strip() or path.stem
            payload["user_id"] = canonical_user_id(user_id)
            users[user_id] = dict(payload)

    legacy_users_root = root / "users"
    if legacy_users_root.exists():
        for user_dir in sorted(path for path in legacy_users_root.iterdir() if path.is_dir()):
            user_id = user_dir.name
            profile = read_json_object(user_dir / "profile.json") or {}
            settings_payload = read_json_object(user_dir / "settings.json") or {}
            if not isinstance(profile, dict):
                profile = {}
            if not isinstance(settings_payload, dict):
                settings_payload = {}
            merged = dict(users.get(user_id, {}))
            merged.update(profile)
            merged["user_id"] = canonical_user_id(user_id)
            if settings_payload:
                merged["settings"] = settings_payload
            users[user_id] = merged

    return [payload for payload in users.values() if isinstance(payload, dict)]


def _legacy_histories(root: Path) -> list[dict[str, Any]]:
    histories: dict[str, dict[str, Any]] = {}

    for path in _iter_json_files(root / "HISTORY"):
        payload = read_json_object(path)
        if isinstance(payload, dict):
            user_id = str(payload.get("user_id", path.stem)).strip() or path.stem
            payload["user_id"] = canonical_user_id(user_id)
            histories[user_id] = dict(payload)

    legacy_users_root = root / "users"
    if legacy_users_root.exists():
        for user_dir in sorted(path for path in legacy_users_root.iterdir() if path.is_dir()):
            history_dir = user_dir / "history"
            if not history_dir.exists():
                continue
            conversations: list[dict[str, Any]] = []
            for session_file in _iter_json_files(history_dir):
                payload = read_json_object(session_file)
                if isinstance(payload, dict):
                    conversations.append(dict(payload))
            if conversations:
                histories[user_dir.name] = {
                    "user_id": canonical_user_id(user_dir.name),
                    "conversations": conversations,
                }

    return [payload for payload in histories.values() if isinstance(payload, dict)]


def _legacy_feedback(root: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for path in _iter_json_files(root / "FEEDBACK"):
        payload = read_json_object(path)
        if isinstance(payload, dict):
            entries.append(dict(payload))
    return entries


def import_legacy_storage(*, root: Path = DATA_DIR) -> dict[str, int]:
    client = SupabasePersistenceClient(settings.supabase)
    user_repository = UserRepository(client)
    history_repository = HistoryRepository(client)
    feedback_repository = FeedbackRepository(client)

    imported_users = 0
    imported_conversations = 0
    imported_feedback = 0

    imported_user_ids: set[str] = set()

    for user in _legacy_users(root):
        user_repository.save(user)
        imported_user_ids.add(str(user.get("user_id", "")).strip())
        imported_users += 1

    for history_payload in _legacy_histories(root):
        user_id = canonical_user_id(str(history_payload.get("user_id", "")).strip())
        raw_conversations = history_payload.get("conversations", [])
        if not user_id or not isinstance(raw_conversations, list):
            continue
        if user_id not in imported_user_ids:
            placeholder_user = {
                "user_id": user_id,
                "email": f"legacy-{user_id}@nemorax.local",
                "display_name": None,
                "password_hash": "legacy-import",
                "salt": "legacy-import",
                "recovery_answers": {},
                "settings": {},
                "created_at": "1970-01-01T00:00:00+00:00",
                "updated_at": "1970-01-01T00:00:00+00:00",
            }
            user_repository.save(placeholder_user)
            imported_user_ids.add(user_id)
            imported_users += 1

        for conversation in raw_conversations:
            if not isinstance(conversation, dict):
                continue
            record = history_repository.import_conversation(user_id, conversation)
            imported_conversations += 1 if record is not None else 0

    existing_feedback_ids = {
        str(row.get("feedback_id", "")).strip()
        for row in feedback_repository.list(limit=10_000)
        if isinstance(row, dict)
    }
    for entry in _legacy_feedback(root):
        entry = dict(entry)
        if entry.get("user_id"):
            entry["user_id"] = canonical_user_id(str(entry.get("user_id", "")).strip())
            if entry["user_id"] not in imported_user_ids:
                placeholder_user = {
                    "user_id": entry["user_id"],
                    "email": f"legacy-{entry['user_id']}@nemorax.local",
                    "display_name": None,
                    "password_hash": "legacy-import",
                    "salt": "legacy-import",
                    "recovery_answers": {},
                    "settings": {},
                    "created_at": "1970-01-01T00:00:00+00:00",
                    "updated_at": "1970-01-01T00:00:00+00:00",
                }
                user_repository.save(placeholder_user)
                imported_user_ids.add(str(entry["user_id"]))
                imported_users += 1
        feedback_id = str(entry.get("feedback_id", "")).strip()
        if feedback_id and feedback_id in existing_feedback_ids:
            continue
        response = feedback_repository.import_feedback(entry)
        if response.feedback_id:
            imported_feedback += 1

    return {
        "users": imported_users,
        "conversations": imported_conversations,
        "feedback": imported_feedback,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Import legacy JSON storage into Supabase.")
    parser.add_argument(
        "--root",
        default=str(DATA_DIR),
        help="Legacy data root containing USERS/HISTORY/FEEDBACK or data/users.",
    )
    args = parser.parse_args()

    counts = import_legacy_storage(root=Path(args.root).resolve())
    logger.info("Legacy import complete users=%s conversations=%s feedback=%s", counts["users"], counts["conversations"], counts["feedback"])
    print(
        f"Imported users={counts['users']} conversations={counts['conversations']} feedback={counts['feedback']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
