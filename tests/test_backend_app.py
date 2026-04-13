from __future__ import annotations

import json
import sys
import tempfile
import unittest
from urllib.parse import parse_qsl
import uuid
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from nemorax.backend.api.app import create_app
from nemorax.backend.core.settings import ApiSettings, LLMSettings, PathSettings, Settings, SupabaseSettings
from nemorax.backend.llm.base import ChatProvider
from nemorax.backend.llm.models import ChatCompletionResult, LLMMessage, ProviderStatus
from nemorax.backend.repositories import (
    FeedbackRepository,
    HistoryRepository,
    SupabasePersistenceClient,
    UserRepository,
)
from nemorax.backend.runtime import ApplicationServices
from nemorax.backend.services import (
    AuthService,
    ChatService,
    FeedbackService,
    HistoryService,
    KnowledgeBasePromptService,
    SupabaseKnowledgeBaseClient,
)


class StubProvider(ChatProvider):
    def __init__(self) -> None:
        self.last_messages: list[LLMMessage] = []

    @property
    def name(self) -> str:
        return "stub"

    @property
    def model(self) -> str:
        return "stub-model"

    @property
    def base_url(self) -> str:
        return "http://stub-provider.local"

    @property
    def provider_label(self) -> str:
        return "Stub Provider"

    async def chat(self, messages: list[LLMMessage]) -> ChatCompletionResult:
        self.last_messages = list(messages)
        return ChatCompletionResult(
            provider=self.name,
            model=self.model,
            content="Stub reply from the neutral provider layer.",
        )

    async def health(self) -> ProviderStatus:
        return ProviderStatus(
            name=self.name,
            label=self.provider_label,
            model=self.model,
            base_url=self.base_url,
            available=True,
        )


class StubSupabaseKnowledgeBaseClient(SupabaseKnowledgeBaseClient):
    def __init__(self, chunks: list[dict[str, object]]) -> None:
        super().__init__(
            SupabaseSettings(
                url="https://stub-supabase.local",
                anon_key="anon",
                service_role_key="service-role",
                kb_source="supabase",
                timeout_seconds=5.0,
            )
        )
        self._chunks = chunks

    def search_chunks(self, query: str, *, limit: int = 6) -> list[dict[str, object]]:
        del query
        return list(self._chunks[:limit])

    def health(self) -> dict[str, object]:
        return {
            "available": bool(self._chunks),
            "source_path": "supabase://kb_chunks",
            "detail": None,
            "chunk_count": len(self._chunks),
        }


class FakeSupabaseTransport(httpx.MockTransport):
    def __init__(self) -> None:
        self.tables: dict[str, list[dict[str, object]]] = {
            "app_users": [],
            "conversation_sessions": [],
            "conversation_messages": [],
            "feedback_records": [],
        }
        super().__init__(self._handler)

    def _json_response(self, payload: object, status_code: int = 200) -> httpx.Response:
        return httpx.Response(status_code=status_code, json=payload)

    @staticmethod
    def _request_params(request: httpx.Request) -> dict[str, str]:
        return dict(parse_qsl(request.url.query.decode("utf-8"), keep_blank_values=True))

    @staticmethod
    def _parse_filter(raw: str) -> tuple[str, str]:
        operator, _, operand = raw.partition(".")
        return operator, operand

    def _matches(self, row: dict[str, object], params: dict[str, str]) -> bool:
        for column, raw in params.items():
            if column in {"select", "order", "limit", "on_conflict"}:
                continue
            operator, operand = self._parse_filter(raw)
            value = row.get(column)
            if operator == "eq" and str(value) != operand:
                return False
            if operator == "gt" and not (float(value or 0) > float(operand)):
                return False
            if operator == "is":
                if operand == "null" and value is not None:
                    return False
        return True

    def _sort_rows(self, rows: list[dict[str, object]], order: str | None) -> list[dict[str, object]]:
        if not order:
            return rows
        column, _, direction = order.partition(".")
        reverse = direction == "desc"
        return sorted(rows, key=lambda item: item.get(column) or "", reverse=reverse)

    def _upsert_rows(self, table: str, incoming: list[dict[str, object]], *, on_conflict: str) -> list[dict[str, object]]:
        stored = self.tables[table]
        keys = [item.strip() for item in on_conflict.split(",") if item.strip()]
        results: list[dict[str, object]] = []
        for entry in incoming:
            index = next(
                (
                    idx
                    for idx, row in enumerate(stored)
                    if all(str(row.get(key)) == str(entry.get(key)) for key in keys)
                ),
                None,
            )
            if index is None:
                stored.append(dict(entry))
                results.append(dict(entry))
            else:
                stored[index] = {**stored[index], **entry}
                results.append(dict(stored[index]))
        return results

    def _handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        params = self._request_params(request)
        prefer = request.headers.get("Prefer", "")
        if path.startswith("/rest/v1/rpc/append_conversation_messages"):
            payload = json.loads(request.content.decode("utf-8"))
            return self._json_response(self._append_conversation_messages(payload))

        if not path.startswith("/rest/v1/"):
            return self._json_response({"message": "not found"}, 404)

        table = path.removeprefix("/rest/v1/")
        if table not in self.tables:
            return self._json_response({"message": "unknown table"}, 404)

        if request.method == "GET":
            rows = [dict(row) for row in self.tables[table] if self._matches(row, params)]
            rows = self._sort_rows(rows, params.get("order"))
            limit = params.get("limit")
            if limit is not None:
                rows = rows[: int(limit)]
            return self._json_response(rows)

        payload = json.loads(request.content.decode("utf-8")) if request.content else None
        rows_payload = payload if isinstance(payload, list) else [payload]
        rows_payload = [dict(item) for item in rows_payload if isinstance(item, dict)]

        if request.method == "POST":
            if "resolution=merge-duplicates" in prefer:
                result = self._upsert_rows(table, rows_payload, on_conflict=params["on_conflict"])
            else:
                self.tables[table].extend(dict(item) for item in rows_payload)
                result = rows_payload
            return self._json_response([] if "return=minimal" in prefer else result)

        if request.method == "PATCH":
            updated: list[dict[str, object]] = []
            for row in self.tables[table]:
                if self._matches(row, params):
                    row.update(rows_payload[0])
                    updated.append(dict(row))
            return self._json_response([] if "return=minimal" in prefer else updated)

        if request.method == "DELETE":
            kept: list[dict[str, object]] = []
            deleted: list[dict[str, object]] = []
            for row in self.tables[table]:
                if self._matches(row, params):
                    deleted.append(dict(row))
                    if table == "conversation_sessions":
                        session_id = str(row.get("session_id"))
                        self.tables["conversation_messages"] = [
                            message
                            for message in self.tables["conversation_messages"]
                            if str(message.get("session_id")) != session_id
                        ]
                    continue
                kept.append(row)
            self.tables[table] = kept
            return self._json_response([] if "return=minimal" in prefer else deleted)

        return self._json_response({"message": "unsupported"}, 405)

    def _append_conversation_messages(self, payload: dict[str, object]) -> list[dict[str, object]]:
        session_id = str(payload["p_session_id"])
        user_id = str(payload["p_user_id"])
        user_text = str(payload.get("p_user_text") or "").strip()
        assistant_text = str(payload.get("p_assistant_text") or "").strip()
        fallback_title = str(payload.get("p_fallback_title") or "New Chat").strip() or "New Chat"
        message_timestamp = str(payload.get("p_message_timestamp") or "")

        sessions = self.tables["conversation_sessions"]
        session = next(
            (
                row
                for row in sessions
                if str(row.get("session_id")) == session_id and str(row.get("user_id")) == user_id
            ),
            None,
        )
        if session is None:
            session = {
                "session_id": session_id,
                "user_id": user_id,
                "title": fallback_title,
                "message_count": 0,
                "created_at": message_timestamp,
                "updated_at": message_timestamp,
            }
            sessions.append(session)

        messages = self.tables["conversation_messages"]
        sequence = max(
            [int(row.get("sequence") or 0) for row in messages if str(row.get("session_id")) == session_id],
            default=0,
        )
        if user_text:
            sequence += 1
            messages.append(
                {
                    "message_id": str(uuid.uuid4()),
                    "session_id": session_id,
                    "user_id": user_id,
                    "sequence": sequence,
                    "role": "user",
                    "content": user_text,
                    "timestamp": message_timestamp,
                }
            )
            if str(session.get("title") or "New Chat") == "New Chat":
                session["title"] = f"{user_text.replace('\n', ' ')[:40]}..." if len(user_text.replace("\n", " ")) > 40 else user_text.replace("\n", " ")
                if not str(session["title"]).strip():
                    session["title"] = "New Chat"
        if assistant_text:
            sequence += 1
            messages.append(
                {
                    "message_id": str(uuid.uuid4()),
                    "session_id": session_id,
                    "user_id": user_id,
                    "sequence": sequence,
                    "role": "assistant",
                    "content": assistant_text,
                    "timestamp": message_timestamp,
                }
            )
        session["message_count"] = len([row for row in messages if str(row.get("session_id")) == session_id])
        session["updated_at"] = message_timestamp
        return []


def build_test_settings(root: Path) -> Settings:
    data_dir = root / "data"
    paths = PathSettings(
        project_root=root,
        data_dir=data_dir,
        users_dir=data_dir / "USERS",
        history_dir=data_dir / "HISTORY",
        feedback_dir=data_dir / "FEEDBACK",
        knowledge_base_markdown_path=data_dir / "school_info.md",
        knowledge_base_json_path=data_dir / "school_info.json",
        knowledge_base_chunks_path=root / "kb" / "chunks.jsonl",
    )
    api = ApiSettings(
        app_name="Nemorax API",
        app_version="3.0.0",
        environment="test",
        log_level="INFO",
        backend_host="127.0.0.1",
        backend_port=8000,
        backend_url="http://127.0.0.1:8000",
        cors_origins_raw="*",
    )
    llm = LLMSettings(
        provider="groq",
        model="stub-model",
        fallback_model="stub-fallback-model",
        base_url="http://stub-provider.local",
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
    supabase = SupabaseSettings(
        url="https://stub-supabase.local",
        anon_key="anon",
        service_role_key="service-role",
        kb_source="local",
        timeout_seconds=10.0,
    )
    settings = Settings(api=api, llm=llm, supabase=supabase, paths=paths)
    settings.ensure_directories()
    paths.knowledge_base_markdown_path.write_text(
        "Admissions Office: Main campus administration building.\n\nNEMSU is North Eastern Mindanao State University.",
        encoding="utf-8",
    )
    paths.knowledge_base_json_path.write_text(
        json.dumps(
            {
                "institution": {
                    "name": "North Eastern Mindanao State University",
                    "abbreviation": "NEMSU",
                    "formerly_known_as": [
                        "Surigao del Sur State University (SDSSU)",
                        "Surigao del Sur Polytechnic State College (SSPSC)",
                        "Surigao del Sur Polytechnic College (SSPC)",
                        "Bukidnon External Studies Center (BESC)",
                    ],
                },
                "history": {
                    "current_president": "Dr. Nemesio G. Loayon",
                },
                "main_campus_programs": {
                    "college_of_information_technology_education": {
                        "programs": [
                            {"program": "Bachelor of Science in Computer Science"},
                            {"program": "Bachelor of Science in Information Technology"},
                        ]
                    }
                },
                "faq": [
                    {
                        "question": "What programs does Bislig Campus offer?",
                        "answer": (
                            "Bislig Campus offers BS Mechanical Engineering, "
                            "BS Forestry, and BS Civil Engineering."
                        ),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    paths.knowledge_base_chunks_path.parent.mkdir(parents=True, exist_ok=True)
    paths.knowledge_base_chunks_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "chunk_id": "chunk_directory",
                        "page_id": "page_directory",
                        "url": "https://www.nemsu.edu.ph/directory",
                        "title": "Directory",
                        "heading_path": ["Directory"],
                        "page_type": "directory",
                        "topic": "Directory",
                        "raw_text": "Admissions Office: Main campus administration building. Registrar: registrarmain@nemsu.edu.ph.",
                        "normalized_text": "admissions office main campus administration building registrar registrarmain nemsu edu ph",
                        "short_summary": "Admissions and registrar contact information.",
                        "keywords": ["admissions", "registrar", "directory", "office"],
                        "entities": [],
                        "publication_date": None,
                        "updated_date": None,
                        "freshness": "evergreen",
                        "content_hash": "hash-directory",
                        "previous_chunk_id": None,
                        "next_chunk_id": None,
                        "parent_chunk_id": None,
                        "source_section_id": "section-directory",
                    }
                ),
                json.dumps(
                    {
                        "chunk_id": "chunk_campuses",
                        "page_id": "page_about",
                        "url": "https://www.nemsu.edu.ph/about",
                        "title": "Campuses",
                        "heading_path": ["Campuses"],
                        "page_type": "campus_info",
                        "topic": "Campuses",
                        "raw_text": "NEMSU has campuses in Tandag, Cantilan, Lianga, Tagbina, San Miguel, Cagwait, and Bislig.",
                        "normalized_text": "nemsu has campuses in tandag cantilan lianga tagbina san miguel cagwait and bislig",
                        "short_summary": "Campus list.",
                        "keywords": ["campuses", "tandag", "cantilan", "bislig"],
                        "entities": [],
                        "publication_date": None,
                        "updated_date": None,
                        "freshness": "evergreen",
                        "content_hash": "hash-campuses",
                        "previous_chunk_id": None,
                        "next_chunk_id": None,
                        "parent_chunk_id": None,
                        "source_section_id": "section-campuses",
                    }
                ),
                json.dumps(
                    {
                        "chunk_id": "chunk_history",
                        "page_id": "page_history",
                        "url": "https://www.nemsu.edu.ph/aboutus",
                        "title": "History",
                        "heading_path": ["History"],
                        "page_type": "about",
                        "topic": "History",
                        "raw_text": (
                            "North Eastern Mindanao State University (NEMSU) was formerly known as "
                            "Surigao del Sur State University (SDSSU), Surigao del Sur Polytechnic State College "
                            "(SSPSC), Surigao del Sur Polytechnic College (SSPC), and Bukidnon External Studies Center (BESC). "
                            "The current president is Dr. Nemesio G. Loayon."
                        ),
                        "normalized_text": (
                            "north eastern mindanao state university nemsu was formerly known as surigao del sur state university sdssu "
                            "surigao del sur polytechnic state college sspsc surigao del sur polytechnic college sspc "
                            "and bukidnon external studies center besc the current president is dr nemesio g loayon"
                        ),
                        "short_summary": "Historical names and current president.",
                        "keywords": ["history", "former names", "president", "nemsu"],
                        "entities": [],
                        "publication_date": "2024-01-01",
                        "updated_date": "2024-01-01",
                        "freshness": "evergreen",
                        "content_hash": "hash-history",
                        "previous_chunk_id": None,
                        "next_chunk_id": None,
                        "parent_chunk_id": None,
                        "source_section_id": "section-history",
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )
    return settings


def build_test_services(
    settings: Settings,
    provider: StubProvider,
    transport: FakeSupabaseTransport,
) -> ApplicationServices:
    persistence_client = SupabasePersistenceClient(settings.supabase, transport=transport)
    user_repository = UserRepository(persistence_client)
    history_repository = HistoryRepository(persistence_client)
    feedback_repository = FeedbackRepository(persistence_client)
    auth_service = AuthService(user_repository)
    history_service = HistoryService(history_repository)
    feedback_service = FeedbackService(feedback_repository)
    prompt_service = KnowledgeBasePromptService(
        settings.paths.knowledge_base_markdown_path,
        chunks_path=settings.paths.knowledge_base_chunks_path,
    )
    chat_service = ChatService(
        settings=settings,
        provider=provider,
        prompt_service=prompt_service,
        history_service=history_service,
    )
    return ApplicationServices(
        settings=settings,
        user_repository=user_repository,
        history_repository=history_repository,
        feedback_repository=feedback_repository,
        auth_service=auth_service,
        history_service=history_service,
        feedback_service=feedback_service,
        prompt_service=prompt_service,
        llm_provider=provider,
        chat_service=chat_service,
    )


class BackendApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self._tempdir.name)
        self.provider = StubProvider()
        self.transport = FakeSupabaseTransport()
        self.settings = build_test_settings(self.root)
        self.services = build_test_services(self.settings, self.provider, self.transport)
        self.client = TestClient(create_app(services=self.services))

    def tearDown(self) -> None:
        self.client.close()
        self._tempdir.cleanup()

    def test_auth_profile_and_recovery_flow(self) -> None:
        register_response = self.client.post(
            "/api/auth/register",
            json={
                "email": "student@example.com",
                "password": "secret12",
                "recovery_answers": {
                    "favorite color": "blue",
                    "favorite food": "rice",
                },
            },
        )
        self.assertEqual(register_response.status_code, 200)

        login_response = self.client.post(
            "/api/auth/login",
            json={"email": "student@example.com", "password": "secret12"},
        )
        self.assertEqual(login_response.status_code, 200)
        login_payload = login_response.json()
        user_id = login_payload["user_id"]

        profile_response = self.client.get(f"/api/users/{user_id}")
        self.assertEqual(profile_response.status_code, 200)
        self.assertEqual(profile_response.json()["email"], "student@example.com")

        display_name_response = self.client.post(
            f"/api/users/{user_id}/display-name",
            json={"display_name": "Ivan"},
        )
        self.assertEqual(display_name_response.status_code, 200)
        self.assertEqual(display_name_response.json()["display_name"], "Ivan")

        settings_response = self.client.post(
            f"/api/settings/{user_id}",
            json={"theme": "aurora_luxe"},
        )
        self.assertEqual(settings_response.status_code, 200)
        self.assertEqual(settings_response.json()["theme"], "aurora_luxe")

        questions_response = self.client.post(
            "/api/auth/recovery/questions",
            json={"email": "student@example.com"},
        )
        self.assertEqual(questions_response.status_code, 200)
        self.assertEqual(len(questions_response.json()["questions"]), 2)

        verify_response = self.client.post(
            "/api/auth/recovery/verify",
            json={
                "email": "student@example.com",
                "answers": {
                    "favorite color": "blue",
                    "favorite food": "rice",
                },
            },
        )
        self.assertEqual(verify_response.status_code, 200)

        reset_response = self.client.post(
            "/api/auth/recovery/reset",
            json={"email": "student@example.com", "new_password": "newsecret12"},
        )
        self.assertEqual(reset_response.status_code, 200)

        relogin_response = self.client.post(
            "/api/auth/login",
            json={"email": "student@example.com", "password": "newsecret12"},
        )
        self.assertEqual(relogin_response.status_code, 200)

    def test_chat_history_feedback_and_health_routes(self) -> None:
        self.client.post(
            "/api/auth/register",
            json={
                "email": "student@example.com",
                "password": "secret12",
                "recovery_answers": {
                    "favorite color": "blue",
                    "favorite food": "rice",
                },
            },
        )
        login_payload = self.client.post(
            "/api/auth/login",
            json={"email": "student@example.com", "password": "secret12"},
        ).json()
        user_id = login_payload["user_id"]

        chat_response = self.client.post(
            "/api/chat",
            json={
                "session_id": "session-1",
                "user_id": user_id,
                "messages": [{"role": "user", "content": "Where is the admissions office?"}],
            },
        )
        self.assertEqual(chat_response.status_code, 200)
        self.assertEqual(chat_response.json()["reply"], "Stub reply from the neutral provider layer.")
        self.assertTrue(self.provider.last_messages)
        self.assertEqual(self.provider.last_messages[0].role, "system")
        self.assertIn("RETRIEVED KNOWLEDGE CONTEXT", self.provider.last_messages[0].content)

        history_response = self.client.get("/api/history", params={"user_id": user_id})
        self.assertEqual(history_response.status_code, 200)
        history_items = history_response.json()
        self.assertEqual(len(history_items), 1)
        self.assertEqual(history_items[0]["session_id"], "session-1")

        conversation_response = self.client.get("/api/history/session-1", params={"user_id": user_id})
        self.assertEqual(conversation_response.status_code, 200)
        messages = conversation_response.json()["messages"]
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]["role"], "user")
        self.assertEqual(messages[1]["role"], "assistant")

        feedback_response = self.client.post(
            "/api/feedback",
            json={"session_id": "session-1", "comment": "Helpful", "user_id": user_id},
        )
        self.assertEqual(feedback_response.status_code, 200)
        self.assertEqual(feedback_response.json()["message"], "Thank you for your feedback!")

        health_response = self.client.get("/api/health")
        self.assertEqual(health_response.status_code, 200)
        payload = health_response.json()
        self.assertEqual(payload["provider"]["name"], "stub")
        self.assertEqual(payload["provider"]["model"], "stub-model")
        self.assertTrue(payload["provider"]["available"])

        delete_response = self.client.delete("/api/history/session-1", params={"user_id": user_id})
        self.assertEqual(delete_response.status_code, 200)
        self.assertEqual(delete_response.json()["deleted"], "session-1")

    def test_short_follow_up_uses_session_history(self) -> None:
        self.client.post(
            "/api/auth/register",
            json={
                "email": "student@example.com",
                "password": "secret12",
                "recovery_answers": {
                    "favorite color": "blue",
                    "favorite food": "rice",
                },
            },
        )
        user_id = self.client.post(
            "/api/auth/login",
            json={"email": "student@example.com", "password": "secret12"},
        ).json()["user_id"]

        first_response = self.client.post(
            "/api/chat",
            json={
                "session_id": "session-follow-up",
                "user_id": user_id,
                "messages": [{"role": "user", "content": "What was NEMSU called before?"}],
            },
        )
        self.assertEqual(first_response.status_code, 200)

        second_response = self.client.post(
            "/api/chat",
            json={
                "session_id": "session-follow-up",
                "user_id": user_id,
                "messages": [{"role": "user", "content": "what about their year or date"}],
            },
        )
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(second_response.json()["reply"], "Stub reply from the neutral provider layer.")
        self.assertGreaterEqual(len(self.provider.last_messages), 4)
        self.assertEqual(self.provider.last_messages[-1].content, "what about their year or date")

    def test_topic_filter_allows_abbreviation_queries(self) -> None:
        response = self.client.post(
            "/api/chat",
            json={
                "session_id": "session-abbrev",
                "messages": [{"role": "user", "content": "who is dean in cite"}],
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["reply"], "Stub reply from the neutral provider layer.")
        self.assertTrue(self.provider.last_messages)

    def test_topic_filter_allows_typoed_alias_queries(self) -> None:
        response = self.client.post(
            "/api/chat",
            json={
                "session_id": "session-abbrev-typo",
                "messages": [{"role": "user", "content": "who is the dean of citr"}],
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["reply"], "Stub reply from the neutral provider layer.")
        self.assertTrue(self.provider.last_messages)

    def test_topic_filter_allows_identity_queries(self) -> None:
        response = self.client.post(
            "/api/chat",
            json={
                "session_id": "session-identity",
                "messages": [{"role": "user", "content": "what is nemsu"}],
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["reply"], "Stub reply from the neutral provider layer.")
        self.assertTrue(self.provider.last_messages)

    def test_greeting_returns_natural_scoped_reply(self) -> None:
        response = self.client.post(
            "/api/chat",
            json={
                "session_id": "session-greeting",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("NEMSU questions", response.json()["reply"])
        self.assertFalse(self.provider.last_messages)

    def test_in_scope_query_with_weak_retrieval_asks_for_narrowing(self) -> None:
        response = self.client.post(
            "/api/chat",
            json={
                "session_id": "session-weak-retrieval",
                "messages": [{"role": "user", "content": "who is the dean of cbm"}],
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["reply"], "Stub reply from the neutral provider layer.")
        self.assertTrue(self.provider.last_messages)

    def test_topic_filter_rejects_off_topic_queries(self) -> None:
        response = self.client.post(
            "/api/chat",
            json={
                "session_id": "session-off-topic",
                "messages": [{"role": "user", "content": "tell me the latest bitcoin price"}],
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("NEMSU-related questions", response.json()["reply"])
        self.assertFalse(self.provider.last_messages)

    def test_topic_filter_rejects_world_knowledge_with_school_keyword_overlap(self) -> None:
        response = self.client.post(
            "/api/chat",
            json={
                "session_id": "session-world-topic",
                "messages": [{"role": "user", "content": "who is the president of the philippines"}],
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("NEMSU-related questions", response.json()["reply"])
        self.assertFalse(self.provider.last_messages)

    def test_prompt_service_truncates_large_knowledge_base(self) -> None:
        large_kb = "NEMSU campus information. " * 800
        self.settings.paths.knowledge_base_markdown_path.write_text(large_kb, encoding="utf-8")
        prompt_service = KnowledgeBasePromptService(
            self.settings.paths.knowledge_base_markdown_path,
            chunks_path=None,
            max_knowledge_chars=1200,
        )

        prompt = prompt_service.get_system_prompt()

        self.assertIn("scoped campus assistant", prompt)
        self.assertLess(len(prompt), 4200)

    def test_prompt_service_uses_chunk_retrieval_for_query(self) -> None:
        prompt_service = KnowledgeBasePromptService(
            self.settings.paths.knowledge_base_markdown_path,
            chunks_path=self.settings.paths.knowledge_base_chunks_path,
            max_knowledge_chars=1800,
        )

        prompt = prompt_service.get_system_prompt_for_query("What is the registrar email?")

        self.assertIn("registrarmain@nemsu.edu.ph", prompt)
        self.assertIn("Directory", prompt)
        self.assertIn("https://www.nemsu.edu.ph/directory", prompt)

    def test_prompt_service_retrieves_president_and_former_names(self) -> None:
        prompt_service = KnowledgeBasePromptService(
            self.settings.paths.knowledge_base_markdown_path,
            chunks_path=self.settings.paths.knowledge_base_chunks_path,
            max_knowledge_chars=2200,
        )

        president_prompt = prompt_service.get_system_prompt_for_query("Who is the current president of NEMSU?")
        history_prompt = prompt_service.get_system_prompt_for_query("What was NEMSU called before?")

        self.assertIn("Dr. Nemesio G. Loayon", president_prompt)
        self.assertIn("Surigao del Sur State University", history_prompt)
        self.assertIn("Bukidnon External Studies Center", history_prompt)
        self.assertIn("Source: kb/chunks.jsonl", history_prompt)

    def test_prompt_service_retrieves_program_information_for_course_queries(self) -> None:
        prompt_service = KnowledgeBasePromptService(
            self.settings.paths.knowledge_base_markdown_path,
            chunks_path=self.settings.paths.knowledge_base_chunks_path,
            max_knowledge_chars=2200,
        )

        program_prompt = prompt_service.get_system_prompt_for_query("What courses are available?")
        bislig_prompt = prompt_service.get_system_prompt_for_query("What programs does Bislig Campus offer?")

        self.assertIn("Bachelor of Science in Computer Science", program_prompt)
        self.assertIn("Bachelor of Science in Information Technology", program_prompt)
        self.assertIn("BS Mechanical Engineering", bislig_prompt)
        self.assertIn("Bislig Campus", bislig_prompt)

    def test_prompt_service_can_load_supabase_kb(self) -> None:
        supabase_client = StubSupabaseKnowledgeBaseClient(
            [
                {
                    "source": "supabase:entity:cbm",
                    "content": "canonical_name: College of Business and Management\naliases: CBM\ndescription: The dean of the College of Business and Management is Prof. Sample Dean.",
                    "metadata": {
                        "title": "College of Business and Management",
                        "section": "College",
                        "type": "entity",
                    },
                    "_retrieval_score": 12.0,
                }
            ]
        )
        prompt_service = KnowledgeBasePromptService(
            self.settings.paths.knowledge_base_markdown_path,
            chunks_path=None,
            max_knowledge_chars=2200,
            kb_source="supabase",
            supabase_client=supabase_client,
        )

        prompt = prompt_service.get_system_prompt_for_query("who is the dean of cbm")

        self.assertIn("Prof. Sample Dean", prompt)
        self.assertIn("College of Business and Management", prompt)
        self.assertIn("supabase:entity:cbm", prompt)

    def test_prompt_service_supabase_mode_does_not_require_local_kb_files(self) -> None:
        supabase_client = StubSupabaseKnowledgeBaseClient(
            [
                {
                    "source": "supabase:page:directory",
                    "content": "Admissions Office: Main campus administration building.",
                    "metadata": {
                        "title": "Directory",
                        "section": "Directory",
                        "type": "page",
                    },
                    "_retrieval_score": 9.0,
                }
            ]
        )
        prompt_service = KnowledgeBasePromptService(
            None,
            chunks_path=None,
            max_knowledge_chars=1800,
            kb_source="supabase",
            supabase_client=supabase_client,
        )

        prompt = prompt_service.get_system_prompt_for_query("where is the admissions office")
        health = prompt_service.health()

        self.assertIn("Admissions Office", prompt)
        self.assertEqual(health["source_path"], "supabase://kb_chunks")
        self.assertEqual(health["chunk_count"], 1)
