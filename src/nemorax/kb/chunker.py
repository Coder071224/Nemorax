from __future__ import annotations

from .models import ChunkRecord, PageRecord, SectionRecord
from .utils import approx_token_count, normalize_text_for_match, sha256_text, split_words, stable_id, summarize_text, top_keywords


class SemanticChunker:
    def __init__(self, target_tokens: int = 700, overlap_tokens: int = 120) -> None:
        self.target_tokens = target_tokens
        self.overlap_tokens = overlap_tokens
        self.max_words = max(280, int(target_tokens / 1.3))
        self.overlap_words = max(40, int(overlap_tokens / 1.3))

    def _chunk_section(self, page: PageRecord, section: SectionRecord) -> list[ChunkRecord]:
        text = section.text.strip()
        if not text:
            return []
        segments = [text]
        if approx_token_count(text) > self.target_tokens + 150:
            segments = split_words(text, max_words=self.max_words, overlap_words=self.overlap_words)
        chunks: list[ChunkRecord] = []
        for index, segment in enumerate(segments):
            normalized = normalize_text_for_match(segment)
            chunk_id = stable_id("chunk", page.page_id, "|".join(section.heading_path), str(index), normalized[:200])
            chunks.append(
                ChunkRecord(
                    chunk_id=chunk_id,
                    page_id=page.page_id,
                    url=page.url,
                    title=page.title,
                    heading_path=section.heading_path,
                    page_type=page.page_type,
                    raw_text=segment,
                    normalized_text=normalized,
                    short_summary=summarize_text(segment),
                    keywords=top_keywords(segment),
                    entities=[],
                    topic=section.heading_path[-1] if section.heading_path else page.page_type,
                    publication_date=page.publication_date,
                    updated_date=page.updated_date,
                    freshness=page.freshness,
                    content_hash=sha256_text(normalized),
                    parent_chunk_id=None,
                    previous_chunk_id=None,
                    next_chunk_id=None,
                    source_section_id=section.section_id,
                )
            )
        for index, chunk in enumerate(chunks):
            if index > 0:
                chunk.previous_chunk_id = chunks[index - 1].chunk_id
            if index + 1 < len(chunks):
                chunk.next_chunk_id = chunks[index + 1].chunk_id
        return chunks

    def chunk_page(self, page: PageRecord) -> list[ChunkRecord]:
        sections = page.sections or [
            SectionRecord(
                heading_path=[page.title],
                text=page.cleaned_main_body_text,
                section_id=stable_id("section", page.page_id, page.title),
            )
        ]
        chunks: list[ChunkRecord] = []
        for section in sections:
            chunks.extend(self._chunk_section(page, section))
        return chunks
