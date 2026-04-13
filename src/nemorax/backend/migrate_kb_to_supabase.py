"""Import legacy KB files into Supabase-backed school data tables."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from nemorax.backend.core.logging import get_logger
from nemorax.backend.core.settings import settings
from nemorax.backend.repositories.supabase_client import SupabasePersistenceClient


logger = get_logger("nemorax.kb_import")

_BATCH_SIZE = 200


def _clean_text(value: Any) -> str:
    return str(value or "").replace("\x00", "").strip()


def _clean_optional_text(value: Any) -> str | None:
    cleaned = _clean_text(value)
    return cleaned or None


def _clean_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _clean_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_clean_json(item) for item in value]
    if isinstance(value, str):
        return value.replace("\x00", "")
    return value


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))


def _iter_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            raw = line.strip()
            if not raw:
                continue
            payload = json.loads(raw)
            if isinstance(payload, dict):
                rows.append(payload)
    return rows


def _chunked(items: list[dict[str, Any]], size: int = _BATCH_SIZE) -> list[list[dict[str, Any]]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def _normalize_page(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "page_id": _clean_text(row.get("page_id")),
        "url": _clean_text(row.get("url")),
        "canonical_url": _clean_optional_text(row.get("canonical_url")),
        "title": _clean_text(row.get("title")),
        "page_type": _clean_text(row.get("page_type")),
        "freshness": _clean_text(row.get("freshness")),
        "breadcrumb": _clean_json(row.get("breadcrumb")) if isinstance(row.get("breadcrumb"), list) else [],
        "headings": _clean_json(row.get("headings")) if isinstance(row.get("headings"), list) else [],
        "cleaned_main_body_text": _clean_text(row.get("cleaned_main_body_text")),
        "structured_tables": _clean_json(row.get("structured_tables")) if isinstance(row.get("structured_tables"), list) else [],
        "publication_date": _clean_optional_text(row.get("publication_date")),
        "updated_date": _clean_optional_text(row.get("updated_date")),
        "detected_language": _clean_text(row.get("detected_language")),
        "content_hash": _clean_text(row.get("content_hash")),
        "source_domain": _clean_text(row.get("source_domain")),
        "crawl_timestamp": _clean_optional_text(row.get("crawl_timestamp")),
        "extraction_confidence": row.get("extraction_confidence") or 0,
        "source_links": _clean_json(row.get("source_links")) if isinstance(row.get("source_links"), list) else [],
        "duplicate_of": _clean_optional_text(row.get("duplicate_of")),
        "provenance": _clean_json(row.get("provenance")) if isinstance(row.get("provenance"), dict) else {},
    }


def _normalize_chunk(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "chunk_id": _clean_text(row.get("chunk_id")),
        "source_kind": "page",
        "source_ref": _clean_text(row.get("page_id")),
        "page_id": _clean_optional_text(row.get("page_id")),
        "title": _clean_text(row.get("title")),
        "url": _clean_text(row.get("url")),
        "heading_path": _clean_json(row.get("heading_path")) if isinstance(row.get("heading_path"), list) else [],
        "page_type": _clean_text(row.get("page_type")),
        "topic": _clean_text(row.get("topic")),
        "content": _clean_text(row.get("raw_text")),
        "normalized_text": _clean_text(row.get("normalized_text")),
        "short_summary": _clean_text(row.get("short_summary")),
        "keywords": _clean_json(row.get("keywords")) if isinstance(row.get("keywords"), list) else [],
        "entity_ids": _clean_json(row.get("entities")) if isinstance(row.get("entities"), list) else [],
        "publication_date": _clean_optional_text(row.get("publication_date")),
        "updated_date": _clean_optional_text(row.get("updated_date")),
        "freshness": _clean_text(row.get("freshness")),
        "content_hash": _clean_text(row.get("content_hash")),
        "previous_chunk_id": _clean_optional_text(row.get("previous_chunk_id")),
        "next_chunk_id": _clean_optional_text(row.get("next_chunk_id")),
        "parent_chunk_id": _clean_optional_text(row.get("parent_chunk_id")),
        "source_section_id": _clean_optional_text(row.get("source_section_id")),
        "metadata": {},
    }


def _normalize_entity(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "entity_id": _clean_text(row.get("entity_id")),
        "canonical_name": _clean_text(row.get("canonical_name")),
        "entity_type": _clean_text(row.get("entity_type")),
        "description": _clean_optional_text(row.get("description")),
        "source_urls": _clean_json(row.get("source_urls")) if isinstance(row.get("source_urls"), list) else [],
        "metadata": _clean_json(row.get("metadata")) if isinstance(row.get("metadata"), dict) else {},
    }


def _normalize_alias_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str | None, str, str]] = set()
    for row in rows:
        canonical_name = _clean_text(row.get("canonical_name"))
        entity_id = _clean_optional_text(row.get("entity_id"))
        aliases = row.get("aliases")
        if not canonical_name or not isinstance(aliases, list):
            continue
        for alias in aliases:
            cleaned_alias = _clean_text(alias)
            if not cleaned_alias:
                continue
            dedupe_key = (entity_id, canonical_name.lower(), cleaned_alias.lower())
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            normalized.append(
                {
                    "entity_id": entity_id,
                    "canonical_name": canonical_name,
                    "alias": cleaned_alias,
                    "normalized_alias": cleaned_alias.lower(),
                }
            )
    return normalized


def _normalize_relationship(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "relationship_id": _clean_text(row.get("relationship_id")),
        "subject_entity_id": _clean_text(row.get("subject_entity_id")),
        "predicate": _clean_text(row.get("predicate")),
        "object_entity_id": _clean_optional_text(row.get("object_entity_id")),
        "object_name": _clean_optional_text(row.get("object_name")),
        "valid_from": _clean_optional_text(row.get("valid_from")),
        "valid_to": _clean_optional_text(row.get("valid_to")),
        "source_urls": _clean_json(row.get("source_urls")) if isinstance(row.get("source_urls"), list) else [],
        "confidence": row.get("confidence") or 0,
        "notes": _clean_optional_text(row.get("notes")),
    }


def _dedupe_rows(rows: list[dict[str, Any]], key_field: str) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        key = _clean_text(row.get(key_field))
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def _normalize_timeline(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "timeline_id": f"{_clean_text(row.get('entity_id'))}::{_clean_text(row.get('status'))}::{_clean_text(row.get('valid_from'))}",
        "entity_id": _clean_text(row.get("entity_id")),
        "canonical_name": _clean_text(row.get("canonical_name")),
        "aliases": _clean_json(row.get("aliases")) if isinstance(row.get("aliases"), list) else [],
        "valid_from": _clean_optional_text(row.get("valid_from")),
        "valid_to": _clean_optional_text(row.get("valid_to")),
        "status": _clean_text(row.get("status")),
        "source_urls": _clean_json(row.get("source_urls")) if isinstance(row.get("source_urls"), list) else [],
        "source_authority": _clean_text(row.get("source_authority")),
        "confidence": row.get("confidence") or 0,
        "notes": _clean_optional_text(row.get("notes")),
    }


def _legacy_school_info(data_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    json_path = data_root / "school_info.json"
    if not json_path.exists():
        return [], []
    payload = _read_json(json_path)
    if not isinstance(payload, dict):
        return [], []

    chunks: list[dict[str, Any]] = []
    faqs: list[dict[str, Any]] = []
    for key, value in payload.items():
        if key == "faq" and isinstance(value, list):
            for index, faq in enumerate(value, start=1):
                if not isinstance(faq, dict):
                    continue
                question = str(faq.get("question") or "").strip()
                answer = str(faq.get("answer") or "").strip()
                if not question or not answer:
                    continue
                faq_id = f"legacy-faq-{index}"
                faqs.append(
                    {
                        "faq_id": faq_id,
                        "question": question,
                        "answer": answer,
                        "category": str(faq.get("category") or "Legacy FAQ").strip(),
                        "campus": str(faq.get("campus") or "").strip() or None,
                        "metadata": {item_key: item_value for item_key, item_value in faq.items() if item_key not in {"question", "answer", "category", "campus"}},
                        "source_ref": json_path.as_posix(),
                    }
                )
                chunks.append(
                    {
                        "chunk_id": faq_id,
                        "source_kind": "faq",
                        "source_ref": faq_id,
                        "page_id": None,
                        "title": question,
                        "url": "",
                        "heading_path": ["Legacy FAQ"],
                        "page_type": "faq",
                        "topic": "FAQ",
                        "content": f"question: {question}\nanswer: {answer}",
                        "normalized_text": f"{question} {answer}".lower(),
                        "short_summary": answer[:240],
                        "keywords": [],
                        "entity_ids": [],
                        "publication_date": None,
                        "updated_date": None,
                        "freshness": "evergreen",
                        "content_hash": faq_id,
                        "previous_chunk_id": None,
                        "next_chunk_id": None,
                        "parent_chunk_id": None,
                        "source_section_id": None,
                        "metadata": {"source_file": json_path.name},
                    }
                )
            continue

        content = json.dumps(value, ensure_ascii=True, sort_keys=True)
        chunk_id = f"legacy-json-{key}"
        chunks.append(
            {
                "chunk_id": chunk_id,
                "source_kind": "legacy",
                "source_ref": json_path.as_posix(),
                "page_id": None,
                "title": str(key).replace("_", " ").title(),
                "url": "",
                "heading_path": [str(key).replace("_", " ").title()],
                "page_type": "legacy_json",
                "topic": str(key).replace("_", " ").title(),
                "content": content,
                "normalized_text": content.lower(),
                "short_summary": content[:240],
                "keywords": [],
                "entity_ids": [],
                "publication_date": None,
                "updated_date": None,
                "freshness": "evergreen",
                "content_hash": chunk_id,
                "previous_chunk_id": None,
                "next_chunk_id": None,
                "parent_chunk_id": None,
                "source_section_id": None,
                "metadata": {"source_file": json_path.name},
            }
        )
    return chunks, faqs


def _entity_chunks(entities: list[dict[str, Any]], aliases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    alias_map: dict[str, list[str]] = {}
    for row in aliases:
        entity_id = str(row.get("entity_id") or "").strip()
        alias = str(row.get("alias") or "").strip()
        if entity_id and alias:
            alias_map.setdefault(entity_id, []).append(alias)

    chunks: list[dict[str, Any]] = []
    for entity in entities:
        entity_id = str(entity.get("entity_id") or "").strip()
        canonical_name = str(entity.get("canonical_name") or "").strip()
        if not entity_id or not canonical_name:
            continue
        entity_aliases = alias_map.get(entity_id, [])
        metadata = entity.get("metadata") if isinstance(entity.get("metadata"), dict) else {}
        content_parts = [
            f"canonical_name: {canonical_name}",
            f"entity_type: {str(entity.get('entity_type') or '').strip()}",
        ]
        if entity_aliases:
            content_parts.append("aliases: " + ", ".join(entity_aliases))
        description = str(entity.get("description") or "").strip()
        if description:
            content_parts.append(f"description: {description}")
        if metadata:
            content_parts.append("metadata: " + json.dumps(metadata, ensure_ascii=True, sort_keys=True))
        chunks.append(
            {
                "chunk_id": f"entity::{entity_id}",
                "source_kind": "entity",
                "source_ref": entity_id,
                "page_id": None,
                "title": canonical_name,
                "url": "",
                "heading_path": [str(entity.get("entity_type") or "entity").strip().title()],
                "page_type": "entity",
                "topic": str(entity.get("entity_type") or "").strip().title(),
                "content": "\n".join(content_parts),
                "normalized_text": " ".join(content_parts).lower(),
                "short_summary": description[:240] if description else canonical_name,
                "keywords": entity_aliases,
                "entity_ids": [entity_id],
                "publication_date": None,
                "updated_date": None,
                "freshness": "evergreen",
                "content_hash": f"entity::{entity_id}",
                "previous_chunk_id": None,
                "next_chunk_id": None,
                "parent_chunk_id": None,
                "source_section_id": None,
                "metadata": metadata,
            }
        )
    return chunks


def import_kb(*, kb_root: Path, data_root: Path) -> dict[str, int]:
    client = SupabasePersistenceClient(settings.supabase)

    pages = [_normalize_page(row) for row in _iter_jsonl(kb_root / "pages.jsonl")]
    chunks = [_normalize_chunk(row) for row in _iter_jsonl(kb_root / "chunks.jsonl")]
    entities = [_normalize_entity(row) for row in _read_json(kb_root / "entities.json")]
    aliases = _normalize_alias_rows(_read_json(kb_root / "aliases.json"))
    relationships = _dedupe_rows(
        [_normalize_relationship(row) for row in _read_json(kb_root / "relationships.json")],
        "relationship_id",
    )
    timelines = _dedupe_rows(
        [_normalize_timeline(row) for row in _read_json(kb_root / "name_timeline.json")],
        "timeline_id",
    )
    legacy_chunks, faq_rows = _legacy_school_info(data_root)

    chunks.extend(_entity_chunks(entities, aliases))
    chunks.extend(legacy_chunks)

    for batch in _chunked(pages):
        client.upsert("kb_pages", batch, on_conflict="page_id", returning="minimal")
    for batch in _chunked(entities):
        client.upsert("kb_entities", batch, on_conflict="entity_id", returning="minimal")
    for batch in _chunked(aliases):
        client.upsert("kb_aliases", batch, on_conflict="entity_id,normalized_alias", returning="minimal")
    for batch in _chunked(relationships):
        client.upsert("kb_relationships", batch, on_conflict="relationship_id", returning="minimal")
    for batch in _chunked(timelines):
        client.upsert("kb_name_timeline", batch, on_conflict="timeline_id", returning="minimal")
    for batch in _chunked(faq_rows):
        client.upsert("kb_faq", batch, on_conflict="faq_id", returning="minimal")
    for batch in _chunked(chunks):
        client.upsert("kb_chunks", batch, on_conflict="chunk_id", returning="minimal")

    return {
        "pages": len(pages),
        "entities": len(entities),
        "aliases": len(aliases),
        "relationships": len(relationships),
        "timeline_rows": len(timelines),
        "faq_rows": len(faq_rows),
        "chunks": len(chunks),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Import KB JSON/JSONL files into Supabase.")
    parser.add_argument("--kb-root", default="kb", help="Directory containing pages.jsonl, chunks.jsonl, and related files.")
    parser.add_argument("--data-root", default="data", help="Directory containing legacy school_info.json.")
    args = parser.parse_args()

    counts = import_kb(
        kb_root=Path(args.kb_root).resolve(),
        data_root=Path(args.data_root).resolve(),
    )
    logger.info("KB import complete: %s", counts)
    print(json.dumps(counts, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
