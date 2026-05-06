"""Supabase-backed KB retrieval client."""

from __future__ import annotations

from functools import lru_cache
import math
import re
from typing import Any

import httpx

from nemorax.backend.core.logging import get_logger
from nemorax.backend.core.errors import PersistenceError
from nemorax.backend.core.settings import SupabaseSettings
from nemorax.backend.repositories.supabase_client import SupabasePersistenceClient


logger = get_logger("nemorax.supabase_kb")
_SEARCH_RPC_CANDIDATES = ("search_kb_chunks", "search_kb_knowledge")
_VECTOR_RPC_NAME = "match_kb_chunks"
_VECTOR_DIMENSION = 1536
_SOURCE_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
_SOURCE_STOP_TOKENS = {
    "a",
    "an",
    "and",
    "for",
    "in",
    "is",
    "main",
    "nemsu",
    "of",
    "official",
    "page",
    "portal",
    "the",
    "to",
    "url",
    "website",
}
_QUERY_STOP_TOKENS = _SOURCE_STOP_TOKENS | {
    "about",
    "details",
    "find",
    "help",
    "information",
    "me",
    "more",
    "tell",
}
_INSTITUTION_EVIDENCE_STOP_TOKENS = {
    "del",
    "eastern",
    "mindanao",
    "nemsu",
    "north",
    "northeastern",
    "sdssu",
    "state",
    "sur",
    "surigao",
    "university",
}


class EmbeddingError(RuntimeError):
    """Raised when query embeddings are unavailable or unsafe to use."""


class EmbeddingClient:
    def __init__(self, config: SupabaseSettings) -> None:
        self._config = config

    @property
    def enabled(self) -> bool:
        return self._config.embedding_configured

    @property
    def dimension(self) -> int:
        return self._config.embedding_dimension

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text, gemini_task_type="RETRIEVAL_QUERY")

    def embed_document(self, text: str) -> list[float]:
        return self._embed(text, gemini_task_type="RETRIEVAL_DOCUMENT")

    def _embed(self, text: str, *, gemini_task_type: str) -> list[float]:
        if not self.enabled:
            raise EmbeddingError("Embedding provider is not configured.")

        provider = self._config.embedding_provider
        if provider == "gemini":
            values = self._embed_gemini(text, task_type=gemini_task_type)
        elif provider in {"openai-compatible", "openai"}:
            values = self._embed_openai_compatible(text)
        else:
            raise EmbeddingError("Unsupported embedding provider.")

        if len(values) != self.dimension:
            raise EmbeddingError("Embedding provider returned an unexpected vector dimension.")
        if provider == "gemini" and self._config.embedding_model == "gemini-embedding-001":
            values = self._normalize(values)
        return values

    def _embed_gemini(self, text: str, *, task_type: str) -> list[float]:
        url = f"{self._config.embedding_base_url}/v1beta/models/{self._config.embedding_model}:embedContent"
        payload = {
            "taskType": task_type,
            "content": {"parts": [{"text": text}]},
            "output_dimensionality": self.dimension,
        }
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "x-goog-api-key": self._config.embedding_api_key or "",
        }
        raw = self._post_json(url, headers=headers, payload=payload)
        embedding = raw.get("embedding")
        if not isinstance(embedding, dict):
            raise EmbeddingError("Gemini embedding response was invalid.")
        return self._coerce_values(embedding.get("values"))

    def _embed_openai_compatible(self, text: str) -> list[float]:
        url = f"{self._config.embedding_base_url}/embeddings"
        payload: dict[str, Any] = {
            "model": self._config.embedding_model,
            "input": text,
        }
        if self.dimension > 0:
            payload["dimensions"] = self.dimension
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._config.embedding_api_key or ''}",
            "Content-Type": "application/json",
        }
        raw = self._post_json(url, headers=headers, payload=payload)
        data = raw.get("data")
        if not isinstance(data, list) or not data or not isinstance(data[0], dict):
            raise EmbeddingError("OpenAI-compatible embedding response was invalid.")
        return self._coerce_values(data[0].get("embedding"))

    def _post_json(self, url: str, *, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
        try:
            with httpx.Client(timeout=self._config.embedding_timeout_seconds) as client:
                response = client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                raw = response.json()
        except httpx.HTTPStatusError as exc:
            raise EmbeddingError(f"Embedding provider request failed with status {exc.response.status_code}.") from exc
        except httpx.HTTPError as exc:
            raise EmbeddingError("Embedding provider request failed.") from exc
        except ValueError as exc:
            raise EmbeddingError("Embedding provider returned invalid JSON.") from exc
        if not isinstance(raw, dict):
            raise EmbeddingError("Embedding provider returned an invalid payload.")
        return raw

    @staticmethod
    def _coerce_values(raw_values: Any) -> list[float]:
        if not isinstance(raw_values, list):
            raise EmbeddingError("Embedding values were missing.")
        values: list[float] = []
        for value in raw_values:
            if not isinstance(value, (int, float)):
                raise EmbeddingError("Embedding values were invalid.")
            values.append(float(value))
        return values

    @staticmethod
    def _normalize(values: list[float]) -> list[float]:
        magnitude = math.sqrt(sum(value * value for value in values))
        if magnitude <= 0.0:
            raise EmbeddingError("Embedding provider returned a zero vector.")
        return [value / magnitude for value in values]


class SupabaseKnowledgeBaseClient:
    def __init__(self, config: SupabaseSettings, *, embedding_client: EmbeddingClient | None = None) -> None:
        self._config = config
        self._client = SupabasePersistenceClient(config)
        self._embedding_client = embedding_client or EmbeddingClient(config)

    @property
    def enabled(self) -> bool:
        return self._config.configured and self._config.kb_source == "supabase"

    @lru_cache(maxsize=1)
    def alias_map(self) -> dict[str, set[str]]:
        if not self.enabled:
            return {}
        rows = self._client.select(
            "kb_aliases",
            columns="canonical_name,alias,normalized_alias",
            order="canonical_name.asc",
            limit=5000,
        )
        result: dict[str, set[str]] = {}
        for row in rows:
            canonical_name = str(row.get("canonical_name") or "").strip()
            alias = str(row.get("alias") or "").strip()
            if not canonical_name or not alias:
                continue
            result.setdefault(canonical_name.lower(), {canonical_name}).add(alias)
        return result

    def _expanded_query(self, query: str) -> str:
        lowered = query.lower()
        extras: list[str] = []
        for canonical, aliases in self.alias_map().items():
            variants = {canonical, *{alias.lower() for alias in aliases}}
            if any(item and item in lowered for item in variants):
                extras.extend(sorted(aliases))
                extras.append(canonical)
        expanded = " ".join(dict.fromkeys([query.strip(), *extras]))
        return expanded.strip()

    def _broadened_query(self, query: str) -> str:
        expanded = self._expanded_query(query)
        keywords = [
            token
            for token in _SOURCE_TOKEN_PATTERN.findall(expanded.lower())
            if len(token) >= 2 and token not in _QUERY_STOP_TOKENS
        ]
        if not keywords:
            return expanded
        focused = " ".join(dict.fromkeys(keywords))
        return focused if focused and focused != expanded.lower() else expanded

    def _focused_query(self, query: str) -> str:
        expanded = self._expanded_query(query)
        tokens = [
            token
            for token in _SOURCE_TOKEN_PATTERN.findall(expanded.lower())
            if len(token) >= 3 and token not in _QUERY_STOP_TOKENS
        ]
        if not tokens:
            return expanded
        ordered = list(dict.fromkeys(tokens))
        return " ".join(ordered[:8]).strip() or expanded

    def _simplified_query(self, query: str) -> str:
        tokens = [
            token
            for token in _SOURCE_TOKEN_PATTERN.findall((query or "").lower())
            if len(token) >= 3 and token not in _QUERY_STOP_TOKENS
        ]
        return " ".join(list(dict.fromkeys(tokens))[:10]).strip()

    @staticmethod
    def _dedupe_rows(rows: list[dict[str, Any]], *, max_rows: int) -> list[dict[str, Any]]:
        deduped: list[dict[str, Any]] = []
        seen_sources: set[str] = set()
        seen_content_keys: set[str] = set()
        per_url_counts: dict[str, int] = {}

        for row in rows:
            source_key = str(row.get("source") or "").strip()
            content = str(row.get("content") or "").strip()
            content_key = content[:220].lower()
            url = str((row.get("metadata") or {}).get("url") or "").strip()

            if source_key and source_key in seen_sources:
                continue
            if content_key and content_key in seen_content_keys:
                continue
            if url and per_url_counts.get(url, 0) >= 2:
                continue

            deduped.append(row)
            if source_key:
                seen_sources.add(source_key)
            if content_key:
                seen_content_keys.add(content_key)
            if url:
                per_url_counts[url] = per_url_counts.get(url, 0) + 1
            if len(deduped) >= max_rows:
                break
        return deduped

    @staticmethod
    def _has_strong_rows(rows: list[dict[str, Any]]) -> bool:
        if not rows:
            return False
        scores = [float(row.get("_retrieval_score") or 0.0) for row in rows]
        max_score = max(scores, default=0.0)
        total_score = sum(scores[:3])
        return max_score >= 6.0 or total_score >= 10.0 or len([score for score in scores if score >= 4.0]) >= 2

    def _evidence_tokens(self, query: str) -> set[str]:
        return {
            token
            for token in _SOURCE_TOKEN_PATTERN.findall((query or "").lower())
            if len(token) >= 3
            and token not in _QUERY_STOP_TOKENS
            and token not in _INSTITUTION_EVIDENCE_STOP_TOKENS
        }

    def _row_tokens(self, row: dict[str, Any]) -> set[str]:
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        searchable = " ".join(
            item
            for item in (
                str(row.get("content") or ""),
                str(metadata.get("title") or ""),
                str(metadata.get("section") or ""),
                str(metadata.get("topic") or ""),
            )
            if item
        )
        return set(_SOURCE_TOKEN_PATTERN.findall(searchable.lower()))

    def _evidence_summary(self, *, query: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
        if not rows:
            return {
                "evidence": False,
                "query_token_count": 0,
                "matched_token_count": 0,
                "coverage": 0.0,
                "reason": "no_rows",
            }

        scores = [float(row.get("_retrieval_score") or 0.0) for row in rows]
        max_score = max(scores, default=0.0)
        if max_score >= 12.0:
            return {
                "evidence": True,
                "query_token_count": 0,
                "matched_token_count": 0,
                "coverage": 1.0,
                "reason": "high_score",
            }

        query_tokens = self._evidence_tokens(query)
        matched_tokens: set[str] = set()
        for row in rows[:3]:
            matched_tokens.update(query_tokens & self._row_tokens(row))

        coverage = len(matched_tokens) / max(1, len(query_tokens))
        top3_total = sum(scores[:3])
        has_exact_intent_match = self._has_exact_intent_match(query=query, rows=rows[:3])
        evidence = (
            has_exact_intent_match
            or (
                bool(query_tokens)
                and (
                    len(matched_tokens) >= 2
                    or (len(query_tokens) == 1 and len(matched_tokens) == 1 and max_score >= 2.0)
                )
                and (max_score >= 2.0 or top3_total >= 4.5 or coverage >= 0.35)
            )
        )
        return {
            "evidence": evidence,
            "query_token_count": len(query_tokens),
            "matched_token_count": len(matched_tokens),
            "coverage": round(coverage, 3),
            "reason": "exact_intent_match" if has_exact_intent_match else ("token_coverage" if evidence else "low_token_coverage"),
        }

    def _has_exact_intent_match(self, *, query: str, rows: list[dict[str, Any]]) -> bool:
        lowered_query = (query or "").lower()
        if not rows:
            return False
        intents: list[tuple[tuple[str, ...], tuple[str, ...]]] = [
            (("president",), ("president", "nemesio", "loayon")),
            (("registrar",), ("registrar",)),
            (("admission", "admissions"), ("admission", "admissions")),
            (("enroll", "enrollment"), ("enroll", "enrollment", "admission", "registrar", "portal", "myportal")),
            (("grade", "grades"), ("grade", "grades", "registrar", "myportal", "portal")),
            (("portal", "myportal", "login", "password"), ("portal", "myportal", "login", "preenrollment", "lms")),
            (("schedule", "calendar", "class", "exam"), ("schedule", "calendar", "class", "exam", "event")),
            (("room", "building", "location", "where"), ("room", "building", "location", "office", "campus")),
            (("certificate", "document", "cor", "coe", "tor", "transcript", "diploma", "clearance"), ("certificate", "document", "registrar", "clearance", "transcript", "diploma")),
            (("tuition", "fee", "fees", "payment", "cashier", "balance"), ("tuition", "fee", "payment", "cashier", "assessment")),
            (("scholarship", "financial", "assistance", "voucher"), ("scholarship", "financial", "assistance", "grant")),
            (("clinic", "medical", "health", "medcert"), ("clinic", "medical", "health", "certificate")),
            (("library",), ("library", "borrow", "clearance", "resource")),
            (("guidance", "counseling", "mental", "career"), ("guidance", "counseling", "career", "student")),
            (("uniform", "policy", "attendance", "absence", "handbook", "violation"), ("policy", "attendance", "uniform", "handbook", "student")),
            (("thesis", "capstone", "research", "defense"), ("thesis", "capstone", "research", "defense")),
            (("ojt", "internship", "practicum"), ("ojt", "internship", "practicum", "endorsement")),
            (("graduation", "alumni", "diploma"), ("graduation", "alumni", "diploma", "clearance")),
            (("event", "orientation", "seminar", "intramurals"), ("event", "orientation", "seminar", "intramurals", "announcement")),
            (("wifi", "email", "technical", "error", "support"), ("wifi", "email", "technical", "support", "portal")),
            (("dean",), ("dean",)),
            (("program", "programs", "course", "courses"), ("program", "programs", "course", "courses", "bachelor", "master")),
        ]
        for query_terms, row_terms in intents:
            if not any(term in lowered_query for term in query_terms):
                continue
            for row in rows:
                metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
                searchable = " ".join(
                    item
                    for item in (
                        str(row.get("content") or ""),
                        str(metadata.get("title") or ""),
                        str(metadata.get("section") or ""),
                        str(metadata.get("topic") or ""),
                    )
                    if item
                ).lower()
                if any(term in searchable for term in row_terms):
                    return True
        return False

    def _rpc_search(self, function_name: str, *, query: str, limit: int) -> Any:
        return self._client.rpc(
            function_name,
            {"p_query": query, "p_limit": max(1, min(limit, 20))},
        )

    @staticmethod
    def _vector_literal(values: list[float]) -> str:
        return "[" + ",".join(f"{value:.12g}" for value in values) + "]"

    def _rpc_vector_search(self, *, embedding: list[float], limit: int) -> Any:
        return self._client.rpc(
            _VECTOR_RPC_NAME,
            {
                "query_embedding": self._vector_literal(embedding),
                "match_count": max(1, min(limit, 20)),
            },
        )

    def _embedding_readiness(self) -> dict[str, Any]:
        if not self.enabled:
            return {
                "status": "disabled",
                "embedded_chunk_count": 0,
                "embedding_dimensions": [],
                "embedding_models": [],
                "vector_search_function_available": False,
                "detail": "Supabase knowledge base is not enabled.",
            }
        try:
            rows = self._client.select("kb_vector_readiness", limit=1)
        except PersistenceError:
            return self._embedding_readiness_from_chunks()
        row = rows[0] if rows else {}
        embedded_count = int(row.get("embedded_chunk_count", 0) or 0)
        dimensions = row.get("embedding_dimensions")
        dimensions = dimensions if isinstance(dimensions, list) else []
        models = row.get("embedding_models")
        models = models if isinstance(models, list) else []
        function_available = bool(row.get("vector_search_function_available"))
        numeric_dimensions = {
            int(item)
            for item in dimensions
            if isinstance(item, (int, float)) or (isinstance(item, str) and item.isdigit())
        }
        if embedded_count <= 0:
            status = "empty"
        elif _VECTOR_DIMENSION not in numeric_dimensions:
            status = "dimension_mismatch"
        elif not function_available:
            status = "rpc_missing"
        elif self._embedding_client.dimension != _VECTOR_DIMENSION:
            status = "dimension_mismatch"
        else:
            status = "ready"
        return {
            "status": status,
            "embedded_chunk_count": embedded_count,
            "embedding_dimensions": dimensions,
            "embedding_models": models,
            "vector_search_function_available": function_available,
            "detail": None if status == "ready" else "Vector search is not ready; using PostgreSQL full-text and trigram retrieval.",
        }

    def _embedding_readiness_from_chunks(self) -> dict[str, Any]:
        try:
            rows = self._client.select(
                "kb_chunks",
                columns="chunk_id,embedding_model",
                filters={"embedding": ("not.is", None)},
                limit=5000,
            )
            probe = self._client.rpc(
                _VECTOR_RPC_NAME,
                {
                    "query_embedding": self._vector_literal([0.0] * _VECTOR_DIMENSION),
                    "match_count": 1,
                },
            )
            function_available = isinstance(probe, list)
        except PersistenceError:
            return {
                "status": "unknown",
                "embedded_chunk_count": 0,
                "embedding_dimensions": [],
                "embedding_models": [],
                "vector_search_function_available": False,
                "detail": "Vector readiness could not be checked; using PostgreSQL full-text and trigram retrieval.",
            }
        models = sorted(
            {
                str(row.get("embedding_model") or "").strip()
                for row in rows
                if str(row.get("embedding_model") or "").strip()
            }
        )
        embedded_count = len(rows)
        dimensions = [_VECTOR_DIMENSION] if embedded_count > 0 else []
        if embedded_count <= 0:
            status = "empty"
        elif not function_available:
            status = "rpc_missing"
        elif self._embedding_client.dimension != _VECTOR_DIMENSION:
            status = "dimension_mismatch"
        else:
            status = "ready"
        return {
            "status": status,
            "embedded_chunk_count": embedded_count,
            "embedding_dimensions": dimensions,
            "embedding_models": models,
            "vector_search_function_available": function_available,
            "detail": None if status == "ready" else "Vector readiness view is unavailable; checked kb_chunks directly.",
        }

    @staticmethod
    def _phrase_rank_boost(query: str, *, content: str, metadata: dict[str, Any]) -> float:
        query_text = (query or "").lower()
        searchable = " ".join(
            item
            for item in (
                content,
                str(metadata.get("title") or ""),
                str(metadata.get("section") or ""),
                str(metadata.get("topic") or ""),
            )
            if item
        ).lower()
        boost = 0.0
        if "besc" in query_text and (
            "besc" in searchable or "bukidnon external studies center" in searchable
        ):
            boost += 5.0
        if (
            "besc" not in query_text
            and "bukidnon external studies center" in query_text
            and "bukidnon external studies center" in searchable
        ):
            boost += 5.0
        former_name_query = any(
            phrase in query_text
            for phrase in ("called before", "former name", "previous name", "old name")
        )
        if former_name_query and "surigao del sur state university" in searchable:
            boost += 20.0
        if former_name_query and "formerly known" in searchable:
            boost += 12.0
        if "president" in query_text:
            if "president" in searchable:
                boost += 7.0
            if "nemesio" in searchable or "loayon" in searchable:
                boost += 10.0
        if any(term in query_text for term in ("program", "programs", "course", "courses")):
            if any(term in searchable for term in ("bachelor", "master", "program", "course")):
                boost += 4.0
        if any(term in query_text for term in ("enroll", "enrollment")):
            if any(term in searchable for term in ("enroll", "enrollment", "admission", "registrar", "portal", "myportal")):
                boost += 5.0
        if any(term in query_text for term in ("grade", "grades")):
            if any(term in searchable for term in ("grade", "grades", "registrar", "portal", "myportal")):
                boost += 5.0
        if any(term in query_text for term in ("portal", "myportal", "login", "password")):
            if any(term in searchable for term in ("portal", "myportal", "login", "preenrollment", "lms")):
                boost += 5.0
        if any(term in query_text for term in ("certificate", "document", "cor", "coe", "tor", "transcript", "diploma", "clearance")):
            if any(term in searchable for term in ("certificate", "document", "registrar", "transcript", "diploma", "clearance")):
                boost += 5.0
        if any(term in query_text for term in ("tuition", "fee", "fees", "payment", "cashier", "balance")):
            if any(term in searchable for term in ("tuition", "fee", "payment", "cashier", "assessment", "balance")):
                boost += 5.0
        if any(term in query_text for term in ("room", "building", "location", "where")):
            if any(term in searchable for term in ("room", "building", "location", "office", "campus")):
                boost += 4.0
            if "office" in query_text and "office" in searchable:
                boost += 4.0
        if any(term in query_text for term in ("schedule", "calendar", "class", "exam")):
            if any(term in searchable for term in ("schedule", "calendar", "class", "exam", "event")):
                boost += 4.0
        if any(term in query_text for term in ("library", "clinic", "guidance", "scholarship", "graduation")):
            if any(term in searchable for term in ("library", "clinic", "guidance", "scholarship", "graduation")):
                boost += 5.0
        return boost

    def search_chunks(self, query: str, *, limit: int = 6) -> list[dict[str, Any]]:
        return list(self.search_chunks_detailed(query, limit=limit).get("rows") or [])

    def search_chunks_detailed(self, query: str, *, limit: int = 6) -> dict[str, Any]:
        if not self.enabled or not query.strip():
            return {
                "rows": [],
                "passes": [],
                "decision": "disabled" if not self.enabled else "empty_query",
            }

        def _row_from_payload(row: dict[str, Any], *, pass_query: str, vector: bool = False) -> dict[str, Any] | None:
            url = str(row.get("url") or "").strip()
            content = str(row.get("content") or "").strip()
            metadata = row.get("metadata")
            if not isinstance(metadata, dict):
                metadata = {}
            metadata = {
                **metadata,
                "title": str(row.get("title") or metadata.get("title") or "").strip(),
                "section": (
                    " > ".join(item for item in (row.get("heading_path") or []) if isinstance(item, str))
                    or str(row.get("section") or metadata.get("section") or "").strip()
                ),
                "url": url,
                "type": str(row.get("page_type") or metadata.get("type") or "").strip(),
                "topic": str(row.get("topic") or metadata.get("topic") or "").strip(),
                "date": str(row.get("updated_date") or row.get("publication_date") or metadata.get("date") or "").strip(),
                "match_source": str(row.get("source_kind") or metadata.get("match_source") or "").strip(),
            }
            if vector:
                metadata["match_source"] = metadata.get("match_source") or "vector"
                retrieval_score = float(row.get("similarity") or 0.0) * 10.0
            else:
                retrieval_score = float(row.get("rank") or 0.0) + self._phrase_rank_boost(
                    pass_query,
                    content=content,
                    metadata=metadata,
                )
            return {
                "source": f"supabase:{str(row.get('source_kind') or 'kb')}:{str(row.get('source_ref') or row.get('chunk_id') or '').strip()}",
                "content": content,
                "metadata": metadata,
                "_retrieval_score": retrieval_score,
            }

        def _run_pass(pass_name: str, pass_query: str, pass_limit: int) -> dict[str, Any]:
            payload = None
            rpc_name = ""
            last_error: PersistenceError | None = None
            for candidate in _SEARCH_RPC_CANDIDATES:
                rpc_name = candidate
                try:
                    payload = self._rpc_search(candidate, query=pass_query, limit=pass_limit)
                    break
                except PersistenceError as exc:
                    last_error = exc
                    logger.warning("KB RPC %s failed for pass=%s query=%r", candidate, pass_name, pass_query)
                    continue
            if payload is None:
                detail = str(last_error or "rpc_unavailable")
                return {
                    "name": pass_name,
                    "query": pass_query,
                    "rows": [],
                    "candidate_count": 0,
                    "selected_count": 0,
                    "max_score": 0.0,
                    "status": "rpc_unavailable",
                    "rpc_name": rpc_name,
                    "detail": detail,
                }
            if not isinstance(payload, list):
                logger.warning("KB RPC returned unexpected payload type=%s", type(payload).__name__)
                return {
                    "name": pass_name,
                    "query": pass_query,
                    "rows": [],
                    "candidate_count": 0,
                    "selected_count": 0,
                    "max_score": 0.0,
                    "status": "invalid_payload",
                    "rpc_name": rpc_name,
                    "detail": f"invalid_payload:{type(payload).__name__}",
                }

            rows: list[dict[str, Any]] = []
            for row in payload:
                if not isinstance(row, dict):
                    continue
                normalized = _row_from_payload(row, pass_query=pass_query)
                if normalized is not None:
                    rows.append(normalized)
            selected = self._dedupe_rows(
                sorted(rows, key=lambda item: float(item.get("_retrieval_score") or 0.0), reverse=True),
                max_rows=max(1, min(limit + 2, 8)),
            )
            max_score = max((float(item.get("_retrieval_score") or 0.0) for item in selected), default=0.0)
            pass_result = {
                "name": pass_name,
                "query": pass_query,
                "rows": selected,
                "candidate_count": len(payload),
                "selected_count": len(selected),
                "max_score": max_score,
                "status": "ok" if selected else "no_match",
                "rpc_name": rpc_name,
                "detail": None,
            }
            logger.info(
                "KB retrieval pass | name=%s rpc=%s query_chars=%d limit=%d candidates=%d selected=%d max_score=%.3f status=%s",
                pass_name,
                rpc_name,
                len(pass_query),
                pass_limit,
                pass_result["candidate_count"],
                pass_result["selected_count"],
                pass_result["max_score"],
                pass_result["status"],
            )
            return pass_result

        def _run_vector_pass(pass_query: str, pass_limit: int, readiness: dict[str, Any]) -> dict[str, Any]:
            if readiness["status"] != "ready":
                return {
                    "name": "vector",
                    "query": pass_query,
                    "rows": [],
                    "candidate_count": 0,
                    "selected_count": 0,
                    "max_score": 0.0,
                    "status": readiness["status"],
                    "rpc_name": _VECTOR_RPC_NAME,
                    "detail": readiness["detail"],
                }
            if not self._embedding_client.enabled:
                return {
                    "name": "vector",
                    "query": pass_query,
                    "rows": [],
                    "candidate_count": 0,
                    "selected_count": 0,
                    "max_score": 0.0,
                    "status": "embedding_unconfigured",
                    "rpc_name": _VECTOR_RPC_NAME,
                    "detail": "Embedding provider is not configured; using PostgreSQL full-text and trigram retrieval.",
                }
            try:
                embedding = self._embedding_client.embed_query(pass_query)
                payload = self._rpc_vector_search(embedding=embedding, limit=pass_limit)
            except EmbeddingError:
                logger.warning("KB vector search skipped because query embedding failed")
                return {
                    "name": "vector",
                    "query": pass_query,
                    "rows": [],
                    "candidate_count": 0,
                    "selected_count": 0,
                    "max_score": 0.0,
                    "status": "embedding_failed",
                    "rpc_name": _VECTOR_RPC_NAME,
                    "detail": "Embedding provider failed; using PostgreSQL full-text and trigram retrieval.",
                }
            except PersistenceError:
                logger.warning("KB vector RPC failed")
                return {
                    "name": "vector",
                    "query": pass_query,
                    "rows": [],
                    "candidate_count": 0,
                    "selected_count": 0,
                    "max_score": 0.0,
                    "status": "rpc_unavailable",
                    "rpc_name": _VECTOR_RPC_NAME,
                    "detail": "Vector search RPC failed; using PostgreSQL full-text and trigram retrieval.",
                }
            if not isinstance(payload, list):
                return {
                    "name": "vector",
                    "query": pass_query,
                    "rows": [],
                    "candidate_count": 0,
                    "selected_count": 0,
                    "max_score": 0.0,
                    "status": "invalid_payload",
                    "rpc_name": _VECTOR_RPC_NAME,
                    "detail": "Vector search returned an invalid payload; using PostgreSQL full-text and trigram retrieval.",
                }
            rows: list[dict[str, Any]] = []
            for row in payload:
                if not isinstance(row, dict):
                    continue
                normalized = _row_from_payload(row, pass_query=pass_query, vector=True)
                if normalized is not None:
                    rows.append(normalized)
            selected = self._dedupe_rows(
                sorted(rows, key=lambda item: float(item.get("_retrieval_score") or 0.0), reverse=True),
                max_rows=max(1, min(limit + 2, 8)),
            )
            max_score = max((float(item.get("_retrieval_score") or 0.0) for item in selected), default=0.0)
            return {
                "name": "vector",
                "query": pass_query,
                "rows": selected,
                "candidate_count": len(payload),
                "selected_count": len(selected),
                "max_score": max_score,
                "status": "ok" if selected else "no_match",
                "rpc_name": _VECTOR_RPC_NAME,
                "detail": None,
            }

        expanded_query = self._expanded_query(query)
        broadened_query = self._broadened_query(query)
        focused_query = self._focused_query(query)
        simplified_query = self._simplified_query(query)
        embedding_readiness = self._embedding_readiness()
        vector = _run_vector_pass(expanded_query, max(limit, 8), embedding_readiness)
        initial = _run_pass("search", expanded_query, max(limit, 8))
        combined = list(vector["rows"]) + list(initial["rows"])
        passes = [vector, initial]

        if not combined and simplified_query.strip():
            seen_queries = {expanded_query.strip().lower()}
            normalized_simplified = simplified_query.strip().lower()
            if normalized_simplified not in seen_queries:
                simplified = _run_pass("simplified_retry", simplified_query, max(limit + 4, 12))
                passes.append(simplified)
                combined.extend(simplified["rows"])

        should_broaden = not self._has_strong_rows(combined) or len(combined) < 2
        if should_broaden:
            if broadened_query.strip() and broadened_query != expanded_query:
                fallback = _run_pass("fallback", broadened_query, max(limit + 4, 12))
                passes.append(fallback)
                combined.extend(fallback["rows"])

        should_focus = not self._has_strong_rows(combined) or len(combined) < 2
        if should_focus:
            if focused_query.strip() and focused_query not in {expanded_query, broadened_query}:
                deep_fallback = _run_pass("deep_fallback", focused_query, max(limit + 6, 14))
                passes.append(deep_fallback)
                combined.extend(deep_fallback["rows"])

        targeted_queries: list[tuple[str, str]] = []
        lowered_expanded = expanded_query.lower()
        if "president" in lowered_expanded:
            targeted_queries.append(("current_president", "current president"))
            targeted_queries.append(("president_name", "nemesio loayon university president"))
        if any(token in lowered_expanded for token in ("grade", "grades")):
            targeted_queries.append(("student_grades", "student grades registrar myportal portal"))
        if any(token in lowered_expanded for token in ("enroll", "enrollment")):
            targeted_queries.append(("student_enrollment", "student enrollment online enrollment registrar admission"))
        if any(token in lowered_expanded for token in ("portal", "myportal", "login", "password", "account")):
            targeted_queries.append(("student_portal", "student portal myportal login password account preenrollment lms"))
        if any(token in lowered_expanded for token in ("schedule", "calendar", "class", "exam")):
            targeted_queries.append(("school_schedule", "school schedule academic calendar class exam schedule"))
        if any(token in lowered_expanded for token in ("room", "building", "location", "where", "map")):
            targeted_queries.append(("campus_location", "campus office room building location directory map"))
        if any(token in lowered_expanded for token in ("certificate", "document", "cor", "coe", "tor", "transcript", "diploma", "clearance")):
            targeted_queries.append(("student_documents", "registrar certificate document transcript diploma clearance cor coe tor"))
        if any(token in lowered_expanded for token in ("tuition", "fee", "fees", "payment", "cashier", "balance", "receipt")):
            targeted_queries.append(("student_payments", "tuition fee payment cashier assessment balance official receipt"))
        if any(token in lowered_expanded for token in ("scholarship", "financial", "assistance", "voucher", "discount")):
            targeted_queries.append(("student_scholarship", "scholarship financial assistance voucher discount requirements application"))
        if any(token in lowered_expanded for token in ("clinic", "medical", "medcert", "health", "medicine")):
            targeted_queries.append(("clinic_services", "clinic medical certificate health services consultation clearance"))
        if "library" in lowered_expanded:
            targeted_queries.append(("library_services", "library hours borrowing clearance resources online database"))
        if any(token in lowered_expanded for token in ("guidance", "counseling", "mental", "career")):
            targeted_queries.append(("guidance_services", "guidance counseling mental health career appointment services"))
        if any(token in lowered_expanded for token in ("uniform", "policy", "attendance", "absence", "handbook", "violation", "discipline")):
            targeted_queries.append(("student_policy", "student handbook policy attendance uniform discipline violation rules"))
        if any(token in lowered_expanded for token in ("thesis", "capstone", "research", "defense")):
            targeted_queries.append(("research_academic", "thesis capstone research defense adviser manuscript"))
        if any(token in lowered_expanded for token in ("ojt", "internship", "practicum")):
            targeted_queries.append(("internship_ojt", "ojt internship practicum endorsement requirements hours"))
        if any(token in lowered_expanded for token in ("graduation", "alumni", "diploma")):
            targeted_queries.append(("graduation_services", "graduation requirements clearance ceremony diploma alumni"))
        if any(token in lowered_expanded for token in ("announcement", "news", "event", "orientation", "seminar", "intramurals")):
            targeted_queries.append(("school_announcements", "official announcement news event orientation seminar intramurals"))
        if any(token in lowered_expanded for token in ("wifi", "email", "technical", "error", "support", "download", "apk", "windows", "nemis")):
            targeted_queries.append(("technical_support", "technical support wifi school email portal error app download nemis"))
        if "besc" in lowered_expanded or "bukidnon external studies center" in lowered_expanded:
            targeted_queries.append(("alias_besc", "bukidnon external studies center"))
        if (
            ("cite" in lowered_expanded or "college of information technology education" in lowered_expanded)
            and any(token in lowered_expanded for token in ("course", "courses", "program", "programs", "offered"))
        ):
            targeted_queries.append(
                ("cite_programs", "programs offered college information technology education cite")
            )
        if any(phrase in lowered_expanded for phrase in ("called before", "former name", "previous name", "old name")):
            targeted_queries.append(("former_name", "surigao del sur state university nemsu history former name"))
        seen_pass_queries = {str(item["query"]).strip().lower() for item in passes}
        for pass_name, targeted_query in targeted_queries:
            normalized_target = targeted_query.strip().lower()
            if not normalized_target or normalized_target in seen_pass_queries:
                continue
            targeted = _run_pass(pass_name, targeted_query, max(limit + 4, 12))
            passes.append(targeted)
            combined.extend(targeted["rows"])
            seen_pass_queries.add(normalized_target)

        final_rows = self._dedupe_rows(
            sorted(combined, key=lambda item: float(item.get("_retrieval_score") or 0.0), reverse=True),
            max_rows=max(1, min(limit, 8)),
        )
        evidence_summary = self._evidence_summary(query=query, rows=final_rows)
        failure_stage = "none"
        if not final_rows:
            if any(item["status"] == "rpc_unavailable" for item in passes if item["name"] != "vector"):
                failure_stage = "search"
            elif any(item["candidate_count"] > 0 for item in passes):
                failure_stage = "filter"
            else:
                failure_stage = "fallback" if len(passes) > 1 else "search"
        decision = "ranked" if final_rows else "no_match"
        embedding_status = (
            "used"
            if vector["status"] == "ok"
            else (
                vector["status"]
                if vector["status"] in {"embedding_unconfigured", "embedding_failed", "rpc_unavailable", "invalid_payload"}
                else embedding_readiness["status"]
            )
        )
        embedding_detail = vector["detail"] or embedding_readiness["detail"]
        stages = {
            "embedding": {
                "status": embedding_status,
                "detail": embedding_detail,
                "embedded_chunk_count": embedding_readiness["embedded_chunk_count"],
                "embedding_dimensions": embedding_readiness["embedding_dimensions"],
                "vector_search_function_available": embedding_readiness["vector_search_function_available"],
            },
            "search": {
                "status": "ok" if any(item["candidate_count"] > 0 for item in passes if item["name"] != "vector") else "no_match",
                "passes_run": len(passes),
            },
            "rerank": {
                "status": "ok" if combined else "skipped",
                "input_count": len(combined),
                "selected_count": len(final_rows),
            },
            "filter": {
                "status": "ok" if final_rows else "no_match",
                "selected_count": len(final_rows),
            },
            "fallback": {
                "status": "used" if len(passes) > 2 else "skipped",
                "passes": [item["name"] for item in passes[2:]],
            },
            "prompt": {
                "status": "context_ready" if final_rows else "no_context",
            },
        }
        logger.info(
            (
                "KB retrieval summary | source=supabase decision=%s failure_stage=%s passes=%s "
                "combined=%d selected=%d max_score=%.3f evidence=%s"
            ),
            decision,
            failure_stage,
            [item["name"] for item in passes],
            len(combined),
            len(final_rows),
            max((float(item.get("_retrieval_score") or 0.0) for item in final_rows), default=0.0),
            evidence_summary["evidence"],
        )
        return {
            "rows": final_rows,
            "passes": [
                {
                    "name": item["name"],
                    "query": item["query"],
                    "candidate_count": item["candidate_count"],
                    "selected_count": item["selected_count"],
                    "max_score": item["max_score"],
                    "status": item["status"],
                    "rpc_name": item.get("rpc_name"),
                    "detail": item.get("detail"),
                }
                for item in passes
            ],
            "decision": decision,
            "stages": stages,
            "failure_stage": failure_stage,
            "evidence": evidence_summary,
            "query_preprocessing": {
                "raw_query_chars": len(query),
                "expanded_query_chars": len(expanded_query),
                "broadened_query_chars": len(broadened_query),
                "focused_query_chars": len(focused_query),
                "simplified_query_chars": len(simplified_query),
                "alias_expanded": expanded_query.strip().lower() != query.strip().lower(),
            },
        }

    @staticmethod
    def _normalize_source_tokens(text: str) -> set[str]:
        return {
            token
            for token in _SOURCE_TOKEN_PATTERN.findall((text or "").lower())
            if len(token) >= 2 and token not in _SOURCE_STOP_TOKENS
        }

    @lru_cache(maxsize=1)
    def source_rows(self) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        return self._client.select(
            "kb_sources",
            columns="id,source_type,source_name,base_url,category,metadata,active,trust_tier",
            filters={"active": True},
            order="trust_tier.asc",
            limit=5000,
        )

    def best_source_link(self, query: str) -> dict[str, Any] | None:
        if not self.enabled or not query.strip():
            return None

        query_tokens = self._normalize_source_tokens(query)
        if not query_tokens:
            return None

        ranked: list[tuple[float, dict[str, Any]]] = []
        for row in self.source_rows():
            metadata = row.get("metadata")
            if not isinstance(metadata, dict):
                metadata = {}
            access_note = str(metadata.get("access_note") or "").strip().lower()
            if any(marker in access_note for marker in ("known 404", "returns 404", "may be unavailable")):
                continue
            source_name = str(row.get("source_name") or "").strip()
            base_url = str(row.get("base_url") or "").strip()
            category = str(row.get("category") or "").strip()
            search_text = " ".join(
                item
                for item in (
                    source_name,
                    category,
                    base_url,
                    str(metadata.get("seed_url") or "").strip(),
                    access_note,
                )
                if item
            )
            source_tokens = self._normalize_source_tokens(search_text)
            if not source_tokens:
                continue

            overlap = query_tokens & source_tokens
            if not overlap:
                continue

            score = (len(overlap) / max(1, len(query_tokens))) * 10.0
            lowered_query = query.lower()
            lowered_name = source_name.lower()
            lowered_url = base_url.lower()
            if lowered_name and lowered_name in lowered_query:
                score += 5.0
            if any(token in lowered_name for token in query_tokens):
                score += 2.5
            if category and category.lower() in lowered_query:
                score += 1.5
            if "admission" in query_tokens or "admissions" in query_tokens:
                if "admission" in lowered_name or "registrar" in lowered_name:
                    score += 3.0
            if "scholarship" in query_tokens:
                if "scholarship" in lowered_name or "scholarship" in lowered_url:
                    score += 3.0
            if "registrar" in query_tokens and "registrar" in lowered_name:
                score += 3.0
            if "library" in query_tokens and "library" in lowered_name:
                score += 3.0
            if "portal" in query_tokens and any(
                token in lowered_url for token in ("login", "portal", "lms", "preenrollment", "epass")
            ):
                score += 2.0
            ranked.append((score, {**row, "metadata": metadata}))

        if not ranked:
            return None

        ranked.sort(key=lambda item: item[0], reverse=True)
        best_score, best_row = ranked[0]
        if best_score < 4.0:
            return None
        return best_row

    def health(self) -> dict[str, Any]:
        if not self.enabled:
            return {
                "available": False,
                "source_path": "supabase://kb_chunks",
                "detail": "Supabase knowledge base is not configured.",
                "chunk_count": 0,
                "supabase_reachable": False,
                "table_reachable": False,
                "chunk_count_positive": False,
                "embedding_status": "disabled",
                "embedded_chunk_count": 0,
                "embedding_dimensions": [],
                "embedding_models": [],
                "vector_search_function_available": False,
            }
        embedding_readiness = self._embedding_readiness()
        try:
            rows = self._client.select("kb_runtime_stats", limit=1)
            self._client.select("kb_chunks", columns="chunk_id", limit=1)
        except PersistenceError as exc:
            logger.warning("Supabase KB health check failed (%s)", exc)
            return {
                "available": False,
                "source_path": "supabase://kb_chunks",
                "detail": "Supabase knowledge base is unreachable.",
                "chunk_count": 0,
                "supabase_reachable": False,
                "table_reachable": False,
                "chunk_count_positive": False,
                "embedding_status": embedding_readiness["status"],
                "embedded_chunk_count": embedding_readiness["embedded_chunk_count"],
                "embedding_dimensions": embedding_readiness["embedding_dimensions"],
                "embedding_models": embedding_readiness["embedding_models"],
                "vector_search_function_available": embedding_readiness["vector_search_function_available"],
            }
        row = rows[0] if rows else {}
        chunk_count = int(row.get("chunk_count", 0) or 0)
        chunk_count_positive = chunk_count > 0
        return {
            "available": chunk_count_positive,
            "source_path": "supabase://kb_chunks",
            "detail": None if chunk_count_positive else "No KB chunks found in Supabase.",
            "chunk_count": chunk_count,
            "supabase_reachable": True,
            "table_reachable": True,
            "chunk_count_positive": chunk_count_positive,
            "embedding_status": embedding_readiness["status"],
            "embedded_chunk_count": embedding_readiness["embedded_chunk_count"],
            "embedding_dimensions": embedding_readiness["embedding_dimensions"],
            "embedding_models": embedding_readiness["embedding_models"],
            "vector_search_function_available": embedding_readiness["vector_search_function_available"],
        }
