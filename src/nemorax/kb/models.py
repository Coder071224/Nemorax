from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, HttpUrl


class CrawlConfig(BaseModel):
    start_url: HttpUrl
    allowed_domains: list[str]
    optional_document_domains: list[str] = Field(default_factory=list)
    blocked_domains: list[str] = Field(default_factory=list)
    include_patterns: list[str] = Field(default_factory=list)
    exclude_patterns: list[str] = Field(default_factory=list)
    max_pages: int = 250
    max_depth: int = 4
    concurrency: int = 3
    crawl_delay_seconds: float = 1.5
    request_timeout_seconds: int = 20
    retries: int = 2
    user_agent: str = "NEMSU-KB-Bot/1.0 (research and knowledge base generation)"
    same_domain_only: bool = True
    optional_linked_documents_phase: bool = True
    javascript_rendering: bool = False
    chunk_target_tokens: int = 700
    chunk_min_tokens: int = 350
    chunk_max_tokens: int = 950
    chunk_overlap_tokens: int = 90
    output_directory: str = "kb"
    log_directory: str = "logs"
    respect_robots_txt: bool = True


class CrawlRecord(BaseModel):
    page_id: str
    url: str
    normalized_url: str
    final_url: str
    canonical_url: str | None = None
    parent_url: str | None = None
    depth: int = 0
    status_code: int
    content_type: str
    title: str | None = None
    html_path: str | None = None
    discovered_links: list[str] = Field(default_factory=list)
    skipped_reason: str | None = None
    crawl_timestamp: str


class DocumentRecord(BaseModel):
    doc_id: str
    source_page_url: str
    document_url: str
    final_url: str
    title: str | None = None
    document_type_guess: str
    content_type: str | None = None
    page_count: int | None = None
    extracted_text: str = ""
    extraction_confidence: float = 0.0
    file_path: str | None = None
    crawl_timestamp: str
    skipped_reason: str | None = None


class HeadingRecord(BaseModel):
    level: int
    text: str
    anchor: str | None = None


class SectionRecord(BaseModel):
    heading_path: list[str] = Field(default_factory=list)
    text: str
    section_id: str


class PageRecord(BaseModel):
    page_id: str
    url: str
    canonical_url: str | None = None
    title: str
    meta_description: str | None = None
    page_type: str
    freshness: str
    breadcrumb: list[str] = Field(default_factory=list)
    headings: list[HeadingRecord] = Field(default_factory=list)
    sections: list[SectionRecord] = Field(default_factory=list)
    cleaned_main_body_text: str
    structured_tables: list[dict[str, Any]] = Field(default_factory=list)
    publication_date: str | None = None
    updated_date: str | None = None
    detected_language: str
    content_hash: str
    source_domain: str
    crawl_timestamp: str
    extraction_confidence: float
    source_links: list[str] = Field(default_factory=list)
    duplicate_of: str | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)


class ChunkRecord(BaseModel):
    chunk_id: str
    page_id: str
    url: str
    title: str
    heading_path: list[str] = Field(default_factory=list)
    page_type: str
    topic: str
    raw_text: str
    normalized_text: str
    short_summary: str
    keywords: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    publication_date: str | None = None
    updated_date: str | None = None
    freshness: str
    content_hash: str
    previous_chunk_id: str | None = None
    next_chunk_id: str | None = None
    parent_chunk_id: str | None = None
    source_section_id: str | None = None


class EntityRecord(BaseModel):
    entity_id: str
    canonical_name: str
    entity_type: str
    aliases: list[str] = Field(default_factory=list)
    description: str | None = None
    source_urls: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AliasRecord(BaseModel):
    canonical_name: str
    aliases: list[str]
    entity_id: str | None = None
    notes: str | None = None


class RelationshipRecord(BaseModel):
    relationship_id: str
    subject_entity_id: str
    predicate: str
    object_entity_id: str | None = None
    object_name: str | None = None
    valid_from: str | None = None
    valid_to: str | None = None
    source_urls: list[str] = Field(default_factory=list)
    confidence: float = 0.8
    notes: str | None = None


class QaEvalRecord(BaseModel):
    question: str
    intent: str
    supporting_page_ids: list[str] = Field(default_factory=list)
    supporting_chunk_ids: list[str] = Field(default_factory=list)
    supporting_urls: list[str] = Field(default_factory=list)
    notes: str | None = None


class NameTimelineEntry(BaseModel):
    entity_id: str
    canonical_name: str
    aliases: list[str] = Field(default_factory=list)
    valid_from: str | None = None
    valid_to: str | None = None
    status: str
    source_urls: list[str] = Field(default_factory=list)
    source_authority: str
    confidence: float
    notes: str | None = None


class EntityHistoryEntry(BaseModel):
    entity_id: str
    canonical_name: str
    history: list[NameTimelineEntry] = Field(default_factory=list)
