"""Backfill Supabase KB chunk embeddings from the configured backend provider."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import time
from typing import Any

from nemorax.backend.core.settings import load_settings
from nemorax.backend.services.supabase_kb import EmbeddingClient, EmbeddingError, SupabaseKnowledgeBaseClient
from nemorax.backend.repositories.supabase_client import SupabasePersistenceClient


def _chunk_embedding_text(row: dict[str, Any], *, max_chars: int) -> str:
    title = str(row.get("title") or "").strip()
    topic = str(row.get("topic") or "").strip()
    summary = str(row.get("short_summary") or "").strip()
    content = str(row.get("content") or "").strip()
    parts = []
    if title:
        parts.append(f"title: {title}")
    if topic:
        parts.append(f"topic: {topic}")
    if summary:
        parts.append(f"summary: {summary}")
    if content:
        parts.append(f"text: {content}")
    return "\n".join(parts).strip()[:max_chars]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill missing Supabase kb_chunks embeddings.")
    parser.add_argument("--chunk-id", action="append", default=[], help="Specific chunk_id to embed. Can be repeated.")
    parser.add_argument("--limit", type=int, default=0, help="Maximum chunks to embed. Default: all missing chunks.")
    parser.add_argument("--batch-size", type=int, default=25, help="Rows to fetch per Supabase page.")
    parser.add_argument("--retries", type=int, default=1, help="Embedding retries per chunk before skipping.")
    parser.add_argument("--delay-seconds", type=float, default=1.0, help="Pause between successful embedding requests.")
    parser.add_argument("--max-chars", type=int, default=12000, help="Maximum text characters sent per chunk embedding.")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be embedded without calling Gemini.")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    settings = load_settings()
    config = settings.supabase
    if not config.enabled:
        print("Supabase KB is not configured.")
        return 2
    if not config.embedding_configured:
        print("Embedding provider is not configured.")
        return 2

    kb_client = SupabaseKnowledgeBaseClient(config)
    health = kb_client.health()
    if not health.get("vector_search_function_available"):
        print("Vector search SQL is not installed. Apply the vector migrations before backfilling.")
        return 2

    persistence = SupabasePersistenceClient(config)
    embeddings = EmbeddingClient(config)
    batch_size = max(1, min(args.batch_size, 100))
    retries = max(0, args.retries)
    delay_seconds = max(0.0, args.delay_seconds)
    max_chars = max(1000, args.max_chars)
    remaining = args.limit if args.limit and args.limit > 0 else None
    processed = 0
    skipped = 0
    failed: list[str] = []
    last_seen_chunk_id = ""
    target_chunk_ids = [str(item).strip() for item in args.chunk_id if str(item).strip()]

    if target_chunk_ids:
        rows = []
        for chunk_id in target_chunk_ids:
            row = persistence.select_one(
                "kb_chunks",
                columns="chunk_id,title,topic,short_summary,content,embedding",
                filters={"chunk_id": chunk_id},
            )
            if not row:
                print(f"missing chunk_id={chunk_id}")
                skipped += 1
                continue
            if row.get("embedding") is not None:
                print(f"already_embedded chunk_id={chunk_id}")
                skipped += 1
                continue
            rows.append(row)
        remaining = len(rows)
        row_batches = [rows]
    else:
        row_batches = None

    while (row_batches is not None and row_batches) or (row_batches is None and (remaining is None or remaining > 0)):
        page_limit = batch_size if remaining is None else min(batch_size, remaining)
        if row_batches is None:
            filters: dict[str, Any] = {"embedding": None}
            if last_seen_chunk_id:
                filters["chunk_id"] = ("gt", last_seen_chunk_id)
            rows = persistence.select(
                "kb_chunks",
                columns="chunk_id,title,topic,short_summary,content",
                filters=filters,
                order="chunk_id.asc",
                limit=page_limit,
            )
        else:
            rows = row_batches.pop(0)
        if not rows:
            break

        for row in rows:
            chunk_id = str(row.get("chunk_id") or "").strip()
            if chunk_id:
                last_seen_chunk_id = chunk_id
            text = _chunk_embedding_text(row, max_chars=max_chars)
            if not chunk_id or not text:
                skipped += 1
                continue
            if args.dry_run:
                print(f"would_embed chunk_id={chunk_id} chars={len(text)}")
                processed += 1
                continue
            values = None
            for attempt in range(retries + 1):
                try:
                    values = embeddings.embed_document(text)
                    break
                except EmbeddingError as exc:
                    if attempt >= retries:
                        print(f"embedding_failed chunk_id={chunk_id} reason={exc}")
                        failed.append(chunk_id)
                        break
                    wait_seconds = min(2 ** attempt, 4)
                    print(f"embedding_retry chunk_id={chunk_id} attempt={attempt + 1} wait_seconds={wait_seconds}")
                    time.sleep(wait_seconds)
            if values is None:
                skipped += 1
                continue
            persistence.update(
                "kb_chunks",
                {
                    "embedding": SupabaseKnowledgeBaseClient._vector_literal(values),
                    "embedding_model": config.embedding_model,
                    "embedding_updated_at": datetime.now(UTC).isoformat(),
                },
                filters={"chunk_id": chunk_id},
                returning="minimal",
            )
            processed += 1
            print(f"embedded chunk_id={chunk_id} dimension={len(values)}")
            if delay_seconds > 0.0:
                time.sleep(delay_seconds)

        if remaining is not None:
            remaining -= len(rows)

    print(f"done processed={processed} skipped={skipped} failed={len(failed)}")
    if failed:
        print("failed_chunk_ids=" + ",".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
