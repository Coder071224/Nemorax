from __future__ import annotations

from .models import ChunkRecord, CrawlConfig, PageRecord, SectionRecord
from .utils import approx_token_count, clean_text_block, sha256_text, stable_id, summarize_text


def build_chunks(page: PageRecord, config: CrawlConfig) -> list[ChunkRecord]:
    chunks: list[ChunkRecord] = []
    buffer_sections: list[SectionRecord] = []
    buffer_texts: list[str] = []
    previous_chunk_id: str | None = None

    def flush_chunk() -> None:
        nonlocal buffer_sections, buffer_texts, previous_chunk_id
        if not buffer_sections:
            return
        combined_text = "\n\n".join(buffer_texts)
        normalized_text = clean_text_block(combined_text)
        if not normalized_text:
            buffer_sections = []
            buffer_texts = []
            return
        heading_path = list(buffer_sections[0].heading_path)
        chunk_id = stable_id("chunk", page.page_id, "|".join(heading_path), normalized_text[:160])
        chunk = ChunkRecord(
            chunk_id=chunk_id,
            page_id=page.page_id,
            url=page.url,
            title=page.title,
            heading_path=heading_path,
            page_type=page.page_type,
            topic=heading_path[-1] if heading_path else page.page_type,
            raw_text=combined_text,
            normalized_text=normalized_text,
            short_summary=summarize_text(normalized_text, max_words=45),
            keywords=_keywords_from_text(normalized_text, heading_path),
            entities=[],
            publication_date=page.publication_date,
            updated_date=page.updated_date,
            freshness=page.freshness,
            content_hash=sha256_text(normalized_text),
            previous_chunk_id=previous_chunk_id,
            next_chunk_id=None,
            parent_chunk_id=None,
            source_section_id=buffer_sections[0].section_id,
        )
        if chunks:
            chunks[-1].next_chunk_id = chunk_id
        chunks.append(chunk)
        previous_chunk_id = chunk_id
        overlap_text = _build_overlap_text(buffer_texts[-1], config.chunk_overlap_tokens)
        buffer_sections = []
        buffer_texts = [overlap_text] if overlap_text else []

    for section in page.sections:
        section_tokens = approx_token_count(section.text)
        current_tokens = approx_token_count("\n\n".join(buffer_texts))
        if buffer_sections and current_tokens + section_tokens > config.chunk_max_tokens:
            flush_chunk()
        buffer_sections.append(section)
        buffer_texts.append(section.text)
        if approx_token_count("\n\n".join(buffer_texts)) >= config.chunk_target_tokens:
            flush_chunk()
    flush_chunk()
    filtered = [chunk for chunk in chunks if approx_token_count(chunk.normalized_text) >= config.chunk_min_tokens]
    return filtered or chunks[:1]


def _build_overlap_text(text: str, overlap_tokens: int) -> str:
    words = text.split()
    overlap_words = max(0, int(overlap_tokens / 1.3))
    if overlap_words <= 0:
        return ""
    return " ".join(words[-overlap_words:])


def _keywords_from_text(text: str, heading_path: list[str]) -> list[str]:
    words = [word.strip(".,:;()[]").lower() for word in text.split()]
    filtered = [word for word in words if len(word) > 4 and word.isalpha()]
    seen: list[str] = []
    for word in heading_path + filtered:
        clean = word.lower()
        if clean not in seen:
            seen.append(clean)
        if len(seen) >= 12:
            break
    return seen
