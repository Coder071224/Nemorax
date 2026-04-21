"""Supabase-backed KB retrieval client."""

from __future__ import annotations

from functools import lru_cache
import re
from typing import Any

from nemorax.backend.core.logging import get_logger
from nemorax.backend.core.errors import PersistenceError
from nemorax.backend.core.settings import SupabaseSettings
from nemorax.backend.repositories.supabase_client import SupabasePersistenceClient


logger = get_logger("nemorax.supabase_kb")
_SEARCH_RPC_CANDIDATES = ("search_kb_chunks", "search_kb_knowledge")
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
    "current",
    "details",
    "find",
    "help",
    "information",
    "me",
    "more",
    "tell",
}


class SupabaseKnowledgeBaseClient:
    def __init__(self, config: SupabaseSettings) -> None:
        self._config = config
        self._client = SupabasePersistenceClient(config)

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

    def _rpc_search(self, function_name: str, *, query: str, limit: int) -> Any:
        return self._client.rpc(
            function_name,
            {"p_query": query, "p_limit": max(1, min(limit, 20))},
        )

    def search_chunks(self, query: str, *, limit: int = 6) -> list[dict[str, Any]]:
        return list(self.search_chunks_detailed(query, limit=limit).get("rows") or [])

    def search_chunks_detailed(self, query: str, *, limit: int = 6) -> dict[str, Any]:
        if not self.enabled or not query.strip():
            return {
                "rows": [],
                "passes": [],
                "decision": "disabled" if not self.enabled else "empty_query",
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
                rows.append(
                    {
                        "source": f"supabase:{str(row.get('source_kind') or 'kb')}:{str(row.get('source_ref') or row.get('chunk_id') or '').strip()}",
                        "content": content,
                        "metadata": metadata,
                        "_retrieval_score": float(row.get("rank") or 0.0),
                    }
                )
            selected = self._dedupe_rows(
                sorted(rows, key=lambda item: float(item.get("_retrieval_score") or 0.0), reverse=True),
                max_rows=max(1, min(limit + 2, 8)),
            )
            max_score = max((float(item.get("_retrieval_score") or 0.0) for item in selected), default=0.0)
            return {
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

        expanded_query = self._expanded_query(query)
        initial = _run_pass("search", expanded_query, max(limit, 8))
        combined = list(initial["rows"])
        passes = [initial]

        should_broaden = not self._has_strong_rows(combined) or len(combined) < 2
        if should_broaden:
            broadened_query = self._broadened_query(query)
            if broadened_query.strip() and broadened_query != expanded_query:
                fallback = _run_pass("fallback", broadened_query, max(limit + 4, 12))
                passes.append(fallback)
                combined.extend(fallback["rows"])

        should_focus = not self._has_strong_rows(combined) or len(combined) < 2
        if should_focus:
            focused_query = self._focused_query(query)
            if focused_query.strip() and focused_query not in {expanded_query, self._broadened_query(query)}:
                deep_fallback = _run_pass("deep_fallback", focused_query, max(limit + 6, 14))
                passes.append(deep_fallback)
                combined.extend(deep_fallback["rows"])

        final_rows = self._dedupe_rows(
            sorted(combined, key=lambda item: float(item.get("_retrieval_score") or 0.0), reverse=True),
            max_rows=max(1, min(limit, 8)),
        )
        failure_stage = "none"
        if not final_rows:
            if any(item["status"] == "rpc_unavailable" for item in passes):
                failure_stage = "search"
            elif any(item["candidate_count"] > 0 for item in passes):
                failure_stage = "filter"
            else:
                failure_stage = "fallback" if len(passes) > 1 else "search"
        decision = "ranked" if final_rows else "no_match"
        stages = {
            "embedding": {"status": "not_used", "detail": "Using PostgreSQL full-text and trigram retrieval."},
            "search": {
                "status": "ok" if any(item["candidate_count"] > 0 for item in passes) else "no_match",
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
                "status": "used" if len(passes) > 1 else "skipped",
                "passes": [item["name"] for item in passes[1:]],
            },
            "prompt": {
                "status": "context_ready" if final_rows else "no_context",
            },
        }
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
            }
        try:
            rows = self._client.select("kb_runtime_stats", limit=1)
        except PersistenceError as exc:
            logger.warning("Supabase KB health check failed (%s)", exc)
            return {
                "available": False,
                "source_path": "supabase://kb_chunks",
                "detail": "Supabase knowledge base is unreachable.",
                "chunk_count": 0,
            }
        row = rows[0] if rows else {}
        chunk_count = int(row.get("chunk_count", 0) or 0)
        return {
            "available": chunk_count > 0,
            "source_path": "supabase://kb_chunks",
            "detail": None if chunk_count > 0 else "No KB chunks found in Supabase.",
            "chunk_count": chunk_count,
        }
