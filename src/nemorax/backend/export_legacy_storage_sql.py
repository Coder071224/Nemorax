"""Export legacy JSON-backed app data into SQL for manual Supabase import."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from nemorax.backend.config import DATA_DIR
from nemorax.backend.migrate_legacy_storage import (
    _legacy_feedback,
    _legacy_histories,
    _legacy_users,
    canonical_user_id,
)


def _sql_text(value: str | None) -> str:
    if value is None:
        return "NULL"
    return "'" + value.replace("'", "''") + "'"


def _sql_jsonb(value: Any) -> str:
    payload = json.dumps(value if value is not None else {}, ensure_ascii=False)
    return f"{_sql_text(payload)}::jsonb"


def _sql_int(value: Any) -> str:
    if value is None or value == "":
        return "NULL"
    return str(int(value))


def _sql_timestamp(value: Any) -> str:
    if value is None or not str(value).strip():
        return "timezone('utc', now())"
    return _sql_text(str(value).strip())


def _export_users(root: Path) -> list[str]:
    statements: list[str] = []
    for user in _legacy_users(root):
        user_id = canonical_user_id(str(user.get("user_id", "")).strip())
        email = str(user.get("email", "")).strip().lower()
        password_hash = str(user.get("password_hash", "")).strip()
        salt = str(user.get("salt", "")).strip()
        if not user_id or not email or not password_hash or not salt:
            continue
        display_name = user.get("display_name")
        recovery_answers = user.get("recovery_answers", {})
        settings = user.get("settings", {})
        created_at = user.get("created_at")
        updated_at = user.get("updated_at")
        statements.append(
            "\n".join(
                [
                    "insert into public.app_users (",
                    "    user_id, email, display_name, password_hash, salt, recovery_answers, settings, created_at, updated_at",
                    ") values (",
                    f"    {_sql_text(user_id)}::uuid,",
                    f"    {_sql_text(email)},",
                    f"    {_sql_text(str(display_name).strip()) if display_name else 'NULL'},",
                    f"    {_sql_text(password_hash)},",
                    f"    {_sql_text(salt)},",
                    f"    {_sql_jsonb(recovery_answers if isinstance(recovery_answers, dict) else {})},",
                    f"    {_sql_jsonb(settings if isinstance(settings, dict) else {})},",
                    f"    {_sql_timestamp(created_at)}::timestamptz,",
                    f"    {_sql_timestamp(updated_at)}::timestamptz",
                    ")",
                    "on conflict (user_id) do update set",
                    "    email = excluded.email,",
                    "    display_name = excluded.display_name,",
                    "    password_hash = excluded.password_hash,",
                    "    salt = excluded.salt,",
                    "    recovery_answers = excluded.recovery_answers,",
                    "    settings = excluded.settings,",
                    "    created_at = excluded.created_at,",
                    "    updated_at = excluded.updated_at;",
                ]
            )
        )
    return statements


def _export_placeholder_users(root: Path) -> list[str]:
    existing_user_ids = {
        canonical_user_id(str(user.get("user_id", "")).strip())
        for user in _legacy_users(root)
        if str(user.get("email", "")).strip() and str(user.get("password_hash", "")).strip() and str(user.get("salt", "")).strip()
    }
    required_user_ids: set[str] = set()
    for payload in _legacy_histories(root):
        user_id = canonical_user_id(str(payload.get("user_id", "")).strip())
        if user_id:
            required_user_ids.add(user_id)
    for entry in _legacy_feedback(root):
        user_id = canonical_user_id(str(entry.get("user_id", "")).strip()) if entry.get("user_id") else ""
        if user_id:
            required_user_ids.add(user_id)

    statements: list[str] = []
    for user_id in sorted(required_user_ids - existing_user_ids):
        statements.append(
            "\n".join(
                [
                    "insert into public.app_users (",
                    "    user_id, email, display_name, password_hash, salt, recovery_answers, settings, created_at, updated_at",
                    ") values (",
                    f"    {_sql_text(user_id)}::uuid,",
                    f"    {_sql_text(f'legacy-{user_id}@nemorax.local')},",
                    "    NULL,",
                    f"    {_sql_text('legacy-import')},",
                    f"    {_sql_text('legacy-import')},",
                    f"    {_sql_jsonb({})},",
                    f"    {_sql_jsonb({})},",
                    "    '1970-01-01T00:00:00+00:00'::timestamptz,",
                    "    '1970-01-01T00:00:00+00:00'::timestamptz",
                    ")",
                    "on conflict (user_id) do nothing;",
                ]
            )
        )
    return statements


def _normalize_messages(raw_messages: Any) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    if not isinstance(raw_messages, list):
        return messages
    for message in raw_messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role", "")).strip().lower()
        content = str(message.get("content", "")).strip()
        timestamp = str(message.get("timestamp", "")).strip()
        if role not in {"user", "assistant", "system"} or not content:
            continue
        messages.append({"role": role, "content": content, "timestamp": timestamp})
    return messages


def _export_histories(root: Path) -> list[str]:
    statements: list[str] = []
    for payload in _legacy_histories(root):
        user_id = canonical_user_id(str(payload.get("user_id", "")).strip())
        conversations = payload.get("conversations", [])
        if not user_id or not isinstance(conversations, list):
            continue
        for conversation in conversations:
            if not isinstance(conversation, dict):
                continue
            session_id = str(conversation.get("session_id", "")).strip()
            if not session_id:
                continue
            title = str(conversation.get("title", "New Chat")).strip() or "New Chat"
            created_at = conversation.get("created_at")
            updated_at = conversation.get("updated_at")
            messages = _normalize_messages(conversation.get("messages", []))
            statements.append(
                "\n".join(
                    [
                        "insert into public.conversation_sessions (",
                        "    session_id, user_id, title, message_count, created_at, updated_at",
                        ") values (",
                        f"    {_sql_text(session_id)},",
                        f"    {_sql_text(user_id)}::uuid,",
                        f"    {_sql_text(title)},",
                        f"    {len(messages)},",
                        f"    {_sql_timestamp(created_at)}::timestamptz,",
                        f"    {_sql_timestamp(updated_at)}::timestamptz",
                        ")",
                        "on conflict (session_id) do update set",
                        "    user_id = excluded.user_id,",
                        "    title = excluded.title,",
                        "    message_count = excluded.message_count,",
                        "    created_at = excluded.created_at,",
                        "    updated_at = excluded.updated_at;",
                    ]
                )
            )
            statements.append(
                f"delete from public.conversation_messages where session_id = {_sql_text(session_id)} and user_id = {_sql_text(user_id)}::uuid;"
            )
            for index, message in enumerate(messages, start=1):
                statements.append(
                    "\n".join(
                        [
                            "insert into public.conversation_messages (",
                            "    session_id, user_id, sequence, role, content, timestamp",
                            ") values (",
                            f"    {_sql_text(session_id)},",
                            f"    {_sql_text(user_id)}::uuid,",
                            f"    {index},",
                            f"    {_sql_text(message['role'])},",
                            f"    {_sql_text(message['content'])},",
                            f"    {_sql_timestamp(message['timestamp'])}::timestamptz",
                            ")",
                            "on conflict (session_id, sequence) do update set",
                            "    user_id = excluded.user_id,",
                            "    role = excluded.role,",
                            "    content = excluded.content,",
                            "    timestamp = excluded.timestamp;",
                        ]
                    )
                )
    return statements


def _export_feedback(root: Path) -> list[str]:
    statements: list[str] = []
    for entry in _legacy_feedback(root):
        feedback_id = str(entry.get("feedback_id", "")).strip()
        if not feedback_id:
            continue
        session_id = entry.get("session_id")
        rating = entry.get("rating")
        comment = str(entry.get("comment", "") or "")
        category = entry.get("category")
        user_id = canonical_user_id(str(entry.get("user_id", "")).strip()) if entry.get("user_id") else None
        saved_at = entry.get("saved_at")
        statements.append(
            "\n".join(
                [
                    "insert into public.feedback_records (",
                    "    feedback_id, session_id, rating, comment, category, user_id, saved_at",
                    ") values (",
                    f"    {_sql_text(feedback_id)}::uuid,",
                    f"    {_sql_text(str(session_id).strip()) if session_id else 'NULL'},",
                    f"    {_sql_int(rating)},",
                    f"    {_sql_text(comment)},",
                    f"    {_sql_text(str(category).strip()) if category else 'NULL'},",
                    f"    {_sql_text(str(user_id).strip()) + '::uuid' if user_id else 'NULL'},",
                    f"    {_sql_timestamp(saved_at)}::timestamptz",
                    ")",
                    "on conflict (feedback_id) do update set",
                    "    session_id = excluded.session_id,",
                    "    rating = excluded.rating,",
                    "    comment = excluded.comment,",
                    "    category = excluded.category,",
                    "    user_id = excluded.user_id,",
                    "    saved_at = excluded.saved_at;",
                ]
            )
        )
    return statements


def export_sql(*, root: Path, output: Path) -> Path:
    statements = [
        "-- Generated by nemorax.backend.export_legacy_storage_sql",
        "begin;",
        *_export_users(root),
        *_export_placeholder_users(root),
        *_export_histories(root),
        *_export_feedback(root),
        "commit;",
    ]
    output.write_text("\n\n".join(statements) + "\n", encoding="utf-8")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Export legacy JSON-backed app data as SQL.")
    parser.add_argument("--root", default=str(DATA_DIR), help="Legacy data root containing JSON-backed app data.")
    parser.add_argument(
        "--output",
        default="legacy_supabase_import.sql",
        help="Output SQL file path.",
    )
    args = parser.parse_args()
    destination = export_sql(root=Path(args.root).resolve(), output=Path(args.output).resolve())
    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
