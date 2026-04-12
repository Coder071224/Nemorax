from __future__ import annotations

from pathlib import Path
from typing import Any

from .models import ChunkRecord, EntityHistoryEntry, NameTimelineEntry, PageRecord, QaEvalRecord
from .utils import dump_json, iter_jsonl, load_json, utc_now_iso


def validate_kb(output_root: Path) -> dict[str, Any]:
    pages = [PageRecord.model_validate(row) for row in iter_jsonl(output_root / "pages.jsonl")]
    chunks = [ChunkRecord.model_validate(row) for row in iter_jsonl(output_root / "chunks.jsonl")]
    load_json(output_root / "taxonomy.json")
    load_json(output_root / "entities.json")
    load_json(output_root / "aliases.json")
    load_json(output_root / "relationships.json")
    qa_eval = [QaEvalRecord.model_validate(row) for row in load_json(output_root / "qa_eval.json")]
    name_timeline = [NameTimelineEntry.model_validate(row) for row in load_json(output_root / "name_timeline.json")]
    entity_history = [EntityHistoryEntry.model_validate(row) for row in load_json(output_root / "entity_history.json")]

    page_ids = {page.page_id for page in pages}
    chunk_ids = {chunk.chunk_id for chunk in chunks}
    page_ref_errors = [chunk.chunk_id for chunk in chunks if chunk.page_id not in page_ids]
    empty_chunks = [chunk.chunk_id for chunk in chunks if not chunk.normalized_text.strip()]
    empty_pages = [page.page_id for page in pages if not page.cleaned_main_body_text.strip()]
    time_sensitive_without_date = [
        page.page_id
        for page in pages
        if page.freshness == "time-sensitive" and not (page.publication_date or page.updated_date)
    ]
    qa_missing_support = [
        record.question
        for record in qa_eval
        if not record.supporting_page_ids or not all(page_id in page_ids for page_id in record.supporting_page_ids)
    ]
    qa_missing_chunks = [
        record.question
        for record in qa_eval
        if record.supporting_chunk_ids and not all(chunk_id in chunk_ids for chunk_id in record.supporting_chunk_ids)
    ]
    required_names = {
        "Bukidnon External Studies Center",
        "Surigao del Sur Polytechnic College",
        "Surigao del Sur Polytechnic State College",
        "Surigao del Sur State University",
        "North Eastern Mindanao State University",
    }
    timeline_missing = sorted(required_names - {entry.canonical_name for entry in name_timeline})
    summary = {
        "generated_at": utc_now_iso(),
        "page_count": len(pages),
        "chunk_count": len(chunks),
        "qa_eval_count": len(qa_eval),
        "page_reference_errors": page_ref_errors,
        "empty_pages": empty_pages,
        "empty_chunks": empty_chunks,
        "time_sensitive_without_date": time_sensitive_without_date,
        "qa_missing_support": qa_missing_support,
        "qa_missing_chunks": qa_missing_chunks,
        "timeline_missing": timeline_missing,
        "timeline_incomplete": len(name_timeline) < 5 or not entity_history,
        "ok": not any(
            [
                page_ref_errors,
                empty_pages,
                empty_chunks,
                qa_missing_support,
                qa_missing_chunks,
                timeline_missing,
                len(name_timeline) < 5 or not entity_history,
            ]
        ),
    }
    dump_json(output_root / "validation_summary.json", summary)
    return summary
