"""Supabase-backed KB retrieval client."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from nemorax.backend.core.logging import get_logger
from nemorax.backend.core.settings import SupabaseSettings
from nemorax.backend.repositories.supabase_client import SupabasePersistenceClient


logger = get_logger("nemorax.supabase_kb")


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

    def search_chunks(self, query: str, *, limit: int = 6) -> list[dict[str, Any]]:
        if not self.enabled or not query.strip():
            return []
        payload = self._client.rpc(
            "search_kb_chunks",
            {"p_query": self._expanded_query(query), "p_limit": max(1, min(limit, 12))},
        )
        if not isinstance(payload, list):
            logger.warning("KB RPC returned unexpected payload type=%s", type(payload).__name__)
            return []

        rows: list[dict[str, Any]] = []
        for row in payload:
            if not isinstance(row, dict):
                continue
            metadata = row.get("metadata")
            if not isinstance(metadata, dict):
                metadata = {}
            metadata = {
                **metadata,
                "title": str(row.get("title") or metadata.get("title") or "").strip(),
                "section": " > ".join(item for item in (row.get("heading_path") or []) if isinstance(item, str)),
                "url": str(row.get("url") or metadata.get("url") or "").strip(),
                "type": str(row.get("page_type") or metadata.get("type") or "").strip(),
                "topic": str(row.get("topic") or metadata.get("topic") or "").strip(),
                "date": str(row.get("updated_date") or row.get("publication_date") or metadata.get("date") or "").strip(),
            }
            rows.append(
                {
                    "source": f"supabase:{str(row.get('source_kind') or 'kb')}:{str(row.get('source_ref') or row.get('chunk_id') or '').strip()}",
                    "content": str(row.get("content") or "").strip(),
                    "metadata": metadata,
                    "_retrieval_score": float(row.get("rank") or 0.0),
                }
            )
        return rows

    def health(self) -> dict[str, Any]:
        if not self.enabled:
            return {
                "available": False,
                "source_path": "supabase://kb_chunks",
                "detail": "Supabase knowledge base is not configured.",
                "chunk_count": 0,
            }
        rows = self._client.select("kb_runtime_stats", limit=1)
        row = rows[0] if rows else {}
        chunk_count = int(row.get("chunk_count", 0) or 0)
        return {
            "available": chunk_count > 0,
            "source_path": "supabase://kb_chunks",
            "detail": None if chunk_count > 0 else "No KB chunks found in Supabase.",
            "chunk_count": chunk_count,
        }
