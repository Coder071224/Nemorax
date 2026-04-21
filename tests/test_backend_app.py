from __future__ import annotations

import json
import sys
import tempfile
import unittest
import asyncio
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
from nemorax.backend.schemas import ChatRequest, MessageSchema
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


def _response_data(response) -> object:
    payload = response.json()
    assert isinstance(payload, dict)
    assert payload.get("ok") is True
    return payload.get("data")


def _response_error(response) -> dict[str, object]:
    payload = response.json()
    assert isinstance(payload, dict)
    assert payload.get("ok") is False
    error = payload.get("error")
    assert isinstance(error, dict)
    return error


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
    def __init__(
        self,
        chunks: list[dict[str, object]],
        *,
        link_rows: list[dict[str, object]] | None = None,
    ) -> None:
        super().__init__(
            SupabaseSettings(
                url="https://stub-supabase.local",
                service_role_key="service-role",
                kb_source="supabase",
                timeout_seconds=5.0,
            )
        )
        self._chunks = chunks
        self._link_rows = link_rows or []

    def search_chunks(self, query: str, *, limit: int = 6) -> list[dict[str, object]]:
        del query
        return list(self._chunks[:limit])

    def search_chunks_detailed(self, query: str, *, limit: int = 6) -> dict[str, object]:
        rows = self.search_chunks(query, limit=limit)
        return {
            "rows": rows,
            "passes": [
                {
                    "name": "search",
                    "query": query,
                    "candidate_count": len(rows),
                    "selected_count": len(rows),
                    "max_score": max((float(row.get("_retrieval_score") or 0.0) for row in rows), default=0.0),
                    "status": "ok" if rows else "no_match",
                }
            ],
            "decision": "ranked" if rows else "no_match",
        }

    def best_source_link(self, query: str) -> dict[str, object] | None:
        normalized = query.lower()
        for row in self._link_rows:
            haystack = " ".join(
                str(row.get(key) or "")
                for key in ("source_name", "base_url", "category")
            ).lower()
            if any(token in haystack for token in normalized.split()):
                return dict(row)
        return dict(self._link_rows[0]) if self._link_rows else None

    def health(self) -> dict[str, object]:
        return {
            "available": bool(self._chunks),
            "source_path": "supabase://kb_chunks",
            "detail": None,
            "chunk_count": len(self._chunks),
        }


class AdaptiveStubSupabaseKnowledgeBaseClient(StubSupabaseKnowledgeBaseClient):
    def __init__(self, responses: dict[str, list[dict[str, object]]]) -> None:
        super().__init__([])
        self._responses = responses

    def search_chunks(self, query: str, *, limit: int = 6) -> list[dict[str, object]]:
        normalized = " ".join(query.lower().split())
        for key, value in sorted(self._responses.items(), key=lambda item: len(item[0]), reverse=True):
            if key in normalized:
                return list(value[:limit])
        return []

    def search_chunks_detailed(self, query: str, *, limit: int = 6) -> dict[str, object]:
        initial = self.search_chunks(query, limit=limit)
        passes = [
            {
                "name": "search",
                "query": query,
                "candidate_count": len(initial),
                "selected_count": len(initial),
                "max_score": max((float(row.get("_retrieval_score") or 0.0) for row in initial), default=0.0),
                "status": "ok" if initial else "no_match",
            }
        ]
        rows = list(initial)
        if not rows:
            fallback_query = "dean college business management"
            fallback = self.search_chunks(fallback_query, limit=limit)
            passes.append(
                {
                    "name": "fallback",
                    "query": fallback_query,
                    "candidate_count": len(fallback),
                    "selected_count": len(fallback),
                    "max_score": max((float(row.get("_retrieval_score") or 0.0) for row in fallback), default=0.0),
                    "status": "ok" if fallback else "no_match",
                }
            )
            rows.extend(fallback)
        return {
            "rows": rows,
            "passes": passes,
            "decision": "ranked" if rows else "no_match",
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
        login_payload = _response_data(login_response)
        self.assertIsInstance(login_payload, dict)
        user_id = login_payload["user_id"]

        profile_response = self.client.get(f"/api/users/{user_id}")
        self.assertEqual(profile_response.status_code, 200)
        profile_payload = _response_data(profile_response)
        self.assertIsInstance(profile_payload, dict)
        self.assertEqual(profile_payload["email"], "student@example.com")

        display_name_response = self.client.post(
            f"/api/users/{user_id}/display-name",
            json={"display_name": "Ivan"},
        )
        self.assertEqual(display_name_response.status_code, 200)
        display_name_payload = _response_data(display_name_response)
        self.assertIsInstance(display_name_payload, dict)
        self.assertEqual(display_name_payload["display_name"], "Ivan")

        settings_response = self.client.post(
            f"/api/settings/{user_id}",
            json={"theme": "aurora_luxe", "show_splash": False},
        )
        self.assertEqual(settings_response.status_code, 200)
        settings_payload = _response_data(settings_response)
        self.assertIsInstance(settings_payload, dict)
        self.assertEqual(settings_payload["settings"]["theme"], "aurora_luxe")
        self.assertIs(settings_payload["settings"]["show_splash"], False)

        profile_refresh = self.client.get(f"/api/users/{user_id}")
        self.assertEqual(profile_refresh.status_code, 200)
        profile_refresh_payload = _response_data(profile_refresh)
        self.assertIsInstance(profile_refresh_payload, dict)
        self.assertEqual(profile_refresh_payload["settings"]["theme"], "aurora_luxe")
        self.assertIs(profile_refresh_payload["settings"]["show_splash"], False)

        questions_response = self.client.post(
            "/api/auth/recovery/questions",
            json={"email": "student@example.com"},
        )
        self.assertEqual(questions_response.status_code, 200)
        questions_payload = _response_data(questions_response)
        self.assertIsInstance(questions_payload, dict)
        self.assertEqual(len(questions_payload["questions"]), 2)

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
        )
        login_payload = _response_data(login_payload)
        self.assertIsInstance(login_payload, dict)
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
        chat_payload = _response_data(chat_response)
        self.assertIsInstance(chat_payload, dict)
        self.assertEqual(chat_payload["reply"], "Stub reply from the neutral provider layer.")
        self.assertTrue(self.provider.last_messages)
        self.assertEqual(self.provider.last_messages[0].role, "system")
        self.assertNotIn("Admissions Office", self.provider.last_messages[0].content)
        self.assertEqual(self.provider.last_messages[1].role, "assistant")
        self.assertIn("Retrieved knowledge context for this reply", self.provider.last_messages[1].content)
        self.assertIn("Admissions Office", self.provider.last_messages[1].content)

        history_response = self.client.get("/api/history", params={"user_id": user_id})
        self.assertEqual(history_response.status_code, 200)
        history_items = _response_data(history_response)
        self.assertIsInstance(history_items, list)
        self.assertEqual(len(history_items), 1)
        self.assertEqual(history_items[0]["session_id"], "session-1")

        conversation_response = self.client.get("/api/history/session-1", params={"user_id": user_id})
        self.assertEqual(conversation_response.status_code, 200)
        conversation_payload = _response_data(conversation_response)
        self.assertIsInstance(conversation_payload, dict)
        messages = conversation_payload["messages"]
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]["role"], "user")
        self.assertEqual(messages[1]["role"], "assistant")

        feedback_response = self.client.post(
            "/api/feedback",
            json={"session_id": "session-1", "comment": "Helpful", "user_id": user_id},
        )
        self.assertEqual(feedback_response.status_code, 200)
        feedback_payload = _response_data(feedback_response)
        self.assertIsInstance(feedback_payload, dict)
        self.assertEqual(feedback_payload["message"], "Thank you for your feedback!")

        health_response = self.client.get("/api/health")
        self.assertEqual(health_response.status_code, 200)
        payload = _response_data(health_response)
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload["provider"]["name"], "stub")
        self.assertEqual(payload["provider"]["model"], "stub-model")
        self.assertTrue(payload["provider"]["available"])

        delete_response = self.client.delete("/api/history/session-1", params={"user_id": user_id})
        self.assertEqual(delete_response.status_code, 200)
        delete_payload = _response_data(delete_response)
        self.assertIsInstance(delete_payload, dict)
        self.assertEqual(delete_payload["session_id"], "session-1")

    def test_retrieval_preview_route_returns_stage_diagnostics_in_test_env(self) -> None:
        response = self.client.post(
            "/api/chat/retrieval-preview",
            json={
                "session_id": "session-preview",
                "messages": [{"role": "user", "content": "What is the registrar email?"}],
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = _response_data(response)
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload["decision"]["path"], "use_model")
        self.assertEqual(payload["retrieval"]["diagnostics"]["passes"][0]["name"], "search")
        self.assertGreaterEqual(payload["retrieval"]["selected_count"], 1)

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
        )
        user_payload = _response_data(user_id)
        self.assertIsInstance(user_payload, dict)
        user_id = user_payload["user_id"]

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
        second_payload = _response_data(second_response)
        self.assertIsInstance(second_payload, dict)
        self.assertEqual(second_payload["reply"], "Stub reply from the neutral provider layer.")
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
        response_payload = _response_data(response)
        self.assertIsInstance(response_payload, dict)
        self.assertEqual(response_payload["reply"], "Stub reply from the neutral provider layer.")
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
        response_payload = _response_data(response)
        self.assertIsInstance(response_payload, dict)
        self.assertEqual(response_payload["reply"], "Stub reply from the neutral provider layer.")
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
        response_payload = _response_data(response)
        self.assertIsInstance(response_payload, dict)
        self.assertEqual(response_payload["reply"], "Stub reply from the neutral provider layer.")
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
        response_payload = _response_data(response)
        self.assertIsInstance(response_payload, dict)
        self.assertIn("NEMSU questions", response_payload["reply"])
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
        response_payload = _response_data(response)
        self.assertIsInstance(response_payload, dict)
        self.assertEqual(response_payload["reply"], "Stub reply from the neutral provider layer.")
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
        response_payload = _response_data(response)
        self.assertIsInstance(response_payload, dict)
        self.assertIn("NEMSU-related questions", response_payload["reply"])
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
        response_payload = _response_data(response)
        self.assertIsInstance(response_payload, dict)
        self.assertIn("NEMSU-related questions", response_payload["reply"])
        self.assertFalse(self.provider.last_messages)

    def test_auth_failure_uses_standard_error_envelope(self) -> None:
        response = self.client.post(
            "/api/auth/login",
            json={"email": "missing@example.com", "password": "secret12"},
        )

        self.assertEqual(response.status_code, 401)
        error = _response_error(response)
        self.assertEqual(error["code"], "auth_error")
        self.assertEqual(error["message"], "Invalid email or password.")
        self.assertIn("request_id", error)

    def test_not_found_uses_standard_error_envelope(self) -> None:
        response = self.client.get("/api/users/missing-user")

        self.assertEqual(response.status_code, 404)
        error = _response_error(response)
        self.assertEqual(error["code"], "not_found")
        self.assertEqual(error["message"], "User not found")

    def test_request_validation_uses_standard_error_envelope(self) -> None:
        response = self.client.post(
            "/api/chat",
            json={"messages": [{"role": "user", "content": "Hello"}]},
        )

        self.assertEqual(response.status_code, 422)
        error = _response_error(response)
        self.assertEqual(error["code"], "validation_error")
        self.assertEqual(error["message"], "The request payload is invalid.")
        self.assertIsInstance(error["details"], list)

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
        self.assertIn("2026", prompt)
        self.assertLess(len(prompt), 4200)

    def test_prompt_service_uses_chunk_retrieval_for_query(self) -> None:
        prompt_service = KnowledgeBasePromptService(
            self.settings.paths.knowledge_base_markdown_path,
            chunks_path=self.settings.paths.knowledge_base_chunks_path,
            max_knowledge_chars=1800,
        )

        payload = prompt_service.build_prompt_payload("What is the registrar email?")

        self.assertNotIn("registrarmain@nemsu.edu.ph", payload["system_prompt"])
        self.assertIn("registrarmain@nemsu.edu.ph", payload["retrieval_message"])
        self.assertIn("Directory", payload["retrieval_message"])
        self.assertIn("https://www.nemsu.edu.ph/directory", payload["retrieval_message"])

    def test_prompt_service_retrieves_president_and_former_names(self) -> None:
        prompt_service = KnowledgeBasePromptService(
            self.settings.paths.knowledge_base_markdown_path,
            chunks_path=self.settings.paths.knowledge_base_chunks_path,
            max_knowledge_chars=2200,
        )

        president_payload = prompt_service.build_prompt_payload("Who is the current president of NEMSU?")
        history_payload = prompt_service.build_prompt_payload("What was NEMSU called before?")

        self.assertIn("Dr. Nemesio G. Loayon", president_payload["retrieval_message"])
        self.assertIn("Surigao del Sur State University", history_payload["retrieval_message"])
        self.assertIn("Bukidnon External Studies Center", history_payload["retrieval_message"])
        self.assertIn("Source: kb/chunks.jsonl", history_payload["retrieval_message"])

    def test_prompt_service_uses_shared_2026_time_instruction(self) -> None:
        prompt_service = KnowledgeBasePromptService(
            self.settings.paths.knowledge_base_markdown_path,
            chunks_path=self.settings.paths.knowledge_base_chunks_path,
            max_knowledge_chars=2200,
        )

        fallback_prompt = prompt_service.get_system_prompt()
        query_prompt = prompt_service.get_system_prompt_for_query("What is the latest enrollment update?")

        self.assertIn("Treat the present/current context as 2026.", fallback_prompt)
        self.assertIn("do not imply an older present", fallback_prompt)
        self.assertIn("Prefer exact dates", query_prompt)

    def test_prompt_service_retrieves_program_information_for_course_queries(self) -> None:
        prompt_service = KnowledgeBasePromptService(
            self.settings.paths.knowledge_base_markdown_path,
            chunks_path=self.settings.paths.knowledge_base_chunks_path,
            max_knowledge_chars=2200,
        )

        program_payload = prompt_service.build_prompt_payload("What courses are available?")
        bislig_payload = prompt_service.build_prompt_payload("What programs does Bislig Campus offer?")

        self.assertIn("Bachelor of Science in Computer Science", program_payload["retrieval_message"])
        self.assertIn("Bachelor of Science in Information Technology", program_payload["retrieval_message"])
        self.assertIn("BS Mechanical Engineering", bislig_payload["retrieval_message"])
        self.assertIn("Bislig Campus", bislig_payload["retrieval_message"])

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

        payload = prompt_service.build_prompt_payload("who is the dean of cbm")

        self.assertIn("Prof. Sample Dean", payload["retrieval_message"])
        self.assertIn("College of Business and Management", payload["retrieval_message"])
        self.assertIn("supabase:entity:cbm", payload["retrieval_message"])

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

        payload = prompt_service.build_prompt_payload("where is the admissions office")
        health = prompt_service.health()

        self.assertIn("Admissions Office", payload["retrieval_message"])
        self.assertEqual(health["source_path"], "supabase://kb_chunks")
        self.assertEqual(health["chunk_count"], 1)

    def test_prompt_service_keeps_multiple_relevant_chunks_from_same_url(self) -> None:
        supabase_client = StubSupabaseKnowledgeBaseClient(
            [
                {
                    "source": "supabase:page:cbm-1",
                    "content": "College of Business and Management overview and contact details.",
                    "metadata": {
                        "title": "College of Business and Management",
                        "section": "Overview",
                        "type": "page",
                        "url": "https://www.nemsu.edu.ph/academics/colleges/cbm",
                    },
                    "_retrieval_score": 6.0,
                },
                {
                    "source": "supabase:page:cbm-2",
                    "content": "The dean of the College of Business and Management is Prof. Sample Dean.",
                    "metadata": {
                        "title": "College of Business and Management",
                        "section": "Administration",
                        "type": "page",
                        "url": "https://www.nemsu.edu.ph/academics/colleges/cbm",
                    },
                    "_retrieval_score": 5.2,
                },
            ]
        )
        prompt_service = KnowledgeBasePromptService(
            None,
            chunks_path=None,
            kb_source="supabase",
            supabase_client=supabase_client,
        )

        payload = prompt_service.build_prompt_payload("who is the dean of cbm")

        self.assertIn("Prof. Sample Dean", payload["retrieval_message"])
        diagnostics = payload["retrieval_diagnostics"]
        self.assertEqual(diagnostics["selected_count"], 2)

    def test_prompt_service_uses_broader_fallback_retrieval_before_giving_up(self) -> None:
        supabase_client = AdaptiveStubSupabaseKnowledgeBaseClient(
            {
                "cbm": [],
                "dean college business management": [
                    {
                        "source": "supabase:entity:cbm",
                        "content": "The dean of the College of Business and Management is Prof. Sample Dean.",
                        "metadata": {
                            "title": "College of Business and Management",
                            "section": "Leadership",
                            "type": "entity",
                            "url": "https://www.nemsu.edu.ph/academics/colleges/cbm",
                        },
                        "_retrieval_score": 3.0,
                    }
                ],
            }
        )
        prompt_service = KnowledgeBasePromptService(
            None,
            chunks_path=None,
            kb_source="supabase",
            supabase_client=supabase_client,
        )

        payload = prompt_service.build_prompt_payload("who is the dean of cbm")

        self.assertIn("Prof. Sample Dean", payload["retrieval_message"])
        diagnostics = payload["retrieval_diagnostics"]
        self.assertEqual([item["name"] for item in diagnostics["passes"]], ["search", "fallback"])
        self.assertTrue(diagnostics["evidence"])

    def test_chat_returns_single_official_link_when_user_explicitly_requests_it(self) -> None:
        provider = StubProvider()
        prompt_service = KnowledgeBasePromptService(
            None,
            chunks_path=None,
            kb_source="supabase",
            supabase_client=StubSupabaseKnowledgeBaseClient(
                [],
                link_rows=[
                    {
                        "source_name": "Student Admission Requirements",
                        "base_url": "https://www.nemsu.edu.ph/students/admission",
                        "category": "students",
                    }
                ],
            ),
        )
        chat_service = ChatService(
            settings=self.settings,
            provider=provider,
            prompt_service=prompt_service,
            history_service=self.services.history_service,
        )

        response = asyncio.run(
            chat_service.chat(
                ChatRequest(
                    session_id="session-link",
                    messages=[MessageSchema(role="user", content="send me the link for admission requirements")],
                )
            )
        )

        self.assertEqual(
            response.reply,
            "You can find the Student Admission Requirements page here: https://www.nemsu.edu.ph/students/admission",
        )
        self.assertFalse(provider.last_messages)

    def test_chat_uses_one_official_link_when_uncertain(self) -> None:
        provider = StubProvider()
        prompt_service = KnowledgeBasePromptService(
            None,
            chunks_path=None,
            kb_source="supabase",
            supabase_client=StubSupabaseKnowledgeBaseClient(
                [],
                link_rows=[
                    {
                        "source_name": "University Library",
                        "base_url": "https://www.nemsu.edu.ph/academics/library",
                        "category": "academics",
                    }
                ],
            ),
        )
        chat_service = ChatService(
            settings=self.settings,
            provider=provider,
            prompt_service=prompt_service,
            history_service=self.services.history_service,
        )

        response = asyncio.run(
            chat_service.chat(
                ChatRequest(
                    session_id="session-uncertain-link",
                    messages=[MessageSchema(role="user", content="tell me about the library opening details")],
                )
            )
        )

        self.assertEqual(
            response.reply,
            "I'm not fully sure about that yet, but you might find it on the University Library page here: https://www.nemsu.edu.ph/academics/library",
        )
        self.assertFalse(provider.last_messages)

    def test_chat_uncertain_reply_adds_2026_guidance_for_latest_queries(self) -> None:
        provider = StubProvider()
        prompt_service = KnowledgeBasePromptService(
            None,
            chunks_path=None,
            kb_source="supabase",
            supabase_client=StubSupabaseKnowledgeBaseClient([]),
        )
        chat_service = ChatService(
            settings=self.settings,
            provider=provider,
            prompt_service=prompt_service,
            history_service=self.services.history_service,
        )

        response = asyncio.run(
            chat_service.chat(
                ChatRequest(
                    session_id="session-latest-uncertain",
                    messages=[MessageSchema(role="user", content="What is the latest NEMSU scholarship update?")],
                )
            )
        )

        self.assertIn("current NEMSU knowledge base", response.reply)
        self.assertIn("as of 2026", response.reply)
        self.assertFalse(provider.last_messages)
