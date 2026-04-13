"""Minimal server-side Supabase client for knowledge-base records."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import httpx

from nemorax.backend.core.logging import get_logger
from nemorax.backend.core.settings import SupabaseSettings


logger = get_logger("nemorax.supabase_kb")


class SupabaseKnowledgeBaseClient:
    def __init__(self, config: SupabaseSettings) -> None:
        self._config = config

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    def _headers(self) -> dict[str, str]:
        key = self._config.service_role_key or ""
        return {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Accept": "application/json",
        }

    def _fetch_table(self, table: str, select: str) -> list[dict[str, Any]]:
        if not self.enabled:
            return []

        base_url = self._config.url.rstrip("/")
        url = f"{base_url}/rest/v1/{table}"
        params = {"select": select, "order": "id.asc"}
        try:
            with httpx.Client(timeout=self._config.timeout_seconds) as client:
                response = client.get(url, headers=self._headers(), params=params)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Supabase fetch failed for table=%s (%s)", table, exc)
            return []

        payload = response.json()
        if not isinstance(payload, list):
            logger.warning("Supabase table=%s returned unexpected payload type=%s", table, type(payload).__name__)
            return []
        return [row for row in payload if isinstance(row, dict)]

    def fetch_snapshot(self) -> dict[str, Any]:
        entities = self._fetch_table(
            "kb_entities",
            "id,entity_type,canonical_name,campus,title,content,metadata,updated_at",
        )
        aliases = self._fetch_table(
            "kb_aliases",
            "id,entity_id,alias,normalized_alias",
        )
        faqs = self._fetch_table(
            "kb_faq",
            "id,question,answer,category,campus,metadata,updated_at",
        )
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "entities": entities,
                    "aliases": aliases,
                    "faqs": faqs,
                },
                sort_keys=True,
                ensure_ascii=True,
            ).encode("utf-8")
        ).hexdigest()
        return {
            "entities": entities,
            "aliases": aliases,
            "faqs": faqs,
            "fingerprint": fingerprint,
        }
