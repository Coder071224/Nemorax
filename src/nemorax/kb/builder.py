from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from .chunking import build_chunks
from .classification import classify_freshness, classify_page_type
from .dedupe import deduplicate_pages
from .extractor import PageExtractor
from .models import (
    AliasRecord,
    ChunkRecord,
    CrawlConfig,
    CrawlRecord,
    DocumentRecord,
    EntityHistoryEntry,
    EntityRecord,
    NameTimelineEntry,
    PageRecord,
    QaEvalRecord,
    RelationshipRecord,
    SectionRecord,
)
from .utils import clean_text_block, dump_json, ensure_directory, iter_jsonl, sha256_text, stable_id, utc_now_iso, write_jsonl

TIMELINE_SOURCE_URL = "https://www.nemsu.edu.ph/aboutus"
PORTAL_LINKS = {
    "MyPortal": "https://preenrollment.nemsu.edu.ph",
    "LMS": "https://lms.nemsu.edu.ph",
    "ERMS": "https://erms.nemsu.edu.ph",
    "CSMS": "https://csms.nemsu.edu.ph",
    "DTS": "https://dts.nemsu.edu.ph",
    "Itinero": "https://itinero.nemsu.edu.ph/",
    "ePass": "https://epass.nemsu.edu.ph/login",
    "Journal": "https://smrj.nemsu.edu.ph/",
    "Memo": "https://memo.nemsu.edu.ph/",
}
CAMPUS_NAMES = ["Tandag", "Cantilan", "San Miguel", "Cagwait", "Lianga", "Tagbina", "Bislig"]
OFFICE_NAMES = ["Guidance Office", "University Registrar", "University Library", "Admissions", "Public Information Office"]


class KnowledgeBaseBuilder:
    def __init__(self, config: CrawlConfig, output_root: Path):
        self.config = config
        self.output_root = ensure_directory(output_root)
        self.raw_root = ensure_directory(output_root / "raw")
        self.extractor = PageExtractor()

    def build(self) -> dict[str, Any]:
        crawl_records = [CrawlRecord.model_validate(row) for row in iter_jsonl(self.raw_root / "crawl_manifest.jsonl")]
        document_records = [DocumentRecord.model_validate(row) for row in iter_jsonl(self.raw_root / "documents_manifest.jsonl")]
        extracted_pages = [page for page in (self.extractor.extract(record) for record in crawl_records) if page is not None]
        document_pages = [page for page in (self._document_to_page(record) for record in document_records) if page is not None]
        combined_pages, skipped_pages = self._filter_useful_pages(extracted_pages + document_pages)
        pages, duplicates = deduplicate_pages(combined_pages)
        chunks = self._build_chunks_with_entities(pages)
        taxonomy = self._build_taxonomy(pages, chunks)
        entities, aliases, relationships, name_timeline, entity_history = self._build_entities_and_relationships(pages)
        chunks = self._attach_entities_to_chunks(chunks, entities)
        qa_eval = self._build_qa_eval(pages, chunks)
        report = self._build_report(
            crawl_records=crawl_records,
            document_records=document_records,
            pages=pages,
            chunks=chunks,
            duplicates=duplicates,
            skipped_pages=skipped_pages,
            taxonomy=taxonomy,
        )
        self._write_outputs(
            pages=pages,
            chunks=chunks,
            taxonomy=taxonomy,
            entities=entities,
            aliases=aliases,
            relationships=relationships,
            qa_eval=qa_eval,
            report=report,
            name_timeline=name_timeline,
            entity_history=entity_history,
        )
        return {
            "crawl_records": len(crawl_records),
            "document_records": len(document_records),
            "pages": len(pages),
            "chunks": len(chunks),
            "duplicates_removed": len(duplicates),
            "skipped_pages": len(skipped_pages),
        }

    def _document_to_page(self, record: DocumentRecord) -> PageRecord | None:
        if record.skipped_reason or not clean_text_block(record.extracted_text):
            return None
        title = clean_text_block(record.title or record.final_url)
        text = clean_text_block(record.extracted_text)
        page_type = classify_page_type(record.final_url, title, text)
        if page_type == "other":
            page_type = "external_document"
        freshness = classify_freshness(page_type, record.final_url, text)
        return PageRecord(
            page_id=record.doc_id,
            url=record.final_url,
            canonical_url=record.final_url,
            title=title,
            meta_description=None,
            page_type=page_type,
            freshness=freshness,
            breadcrumb=["External Document"],
            headings=[],
            sections=[SectionRecord(heading_path=[title], text=text, section_id=stable_id("section", record.doc_id, title))],
            cleaned_main_body_text=text,
            structured_tables=[],
            publication_date=None,
            updated_date=None,
            detected_language="en",
            content_hash=sha256_text(text),
            source_domain=record.final_url.split("/")[2],
            crawl_timestamp=record.crawl_timestamp,
            extraction_confidence=record.extraction_confidence,
            source_links=[record.source_page_url],
            provenance={
                "source_page_url": record.source_page_url,
                "document_type_guess": record.document_type_guess,
                "file_path": record.file_path,
                "page_count": record.page_count,
            },
        )

    def _filter_useful_pages(self, pages: list[PageRecord]) -> tuple[list[PageRecord], list[dict[str, str]]]:
        useful: list[PageRecord] = []
        skipped: list[dict[str, str]] = []
        for page in pages:
            text = clean_text_block(page.cleaned_main_body_text)
            if len(text) > 1_000_000:
                skipped.append({"page_id": page.page_id, "reason": "oversized low-quality extraction"})
                continue
            if len(text) < 100 and page.page_type in {"other", "gallery/media"}:
                skipped.append({"page_id": page.page_id, "reason": "thin page"})
                continue
            if len(text) < 60:
                skipped.append({"page_id": page.page_id, "reason": "empty or near-empty text"})
                continue
            useful.append(page)
        return useful, skipped

    def _build_chunks_with_entities(self, pages: list[PageRecord]) -> list[ChunkRecord]:
        chunks: list[ChunkRecord] = []
        for page in pages:
            chunks.extend(build_chunks(page, self.config))
        return chunks

    def _build_taxonomy(self, pages: list[PageRecord], chunks: list[ChunkRecord]) -> dict[str, Any]:
        page_type_counts = Counter(page.page_type for page in pages)
        topic_counts = Counter(chunk.topic for chunk in chunks if chunk.topic)
        tree = []
        for page_type, count in page_type_counts.most_common():
            sample_urls = [page.url for page in pages if page.page_type == page_type][:5]
            tree.append({"name": page_type, "count": count, "sample_urls": sample_urls})
        return {
            "root": "North Eastern Mindanao State University",
            "generated_at": utc_now_iso(),
            "page_type_counts": dict(page_type_counts),
            "top_topics": [{"topic": topic, "count": count} for topic, count in topic_counts.most_common(20)],
            "tree": tree,
        }

    def _build_entities_and_relationships(
        self,
        pages: list[PageRecord],
    ) -> tuple[list[EntityRecord], list[AliasRecord], list[RelationshipRecord], list[NameTimelineEntry], list[EntityHistoryEntry]]:
        entities: dict[str, EntityRecord] = {}
        relationships: list[RelationshipRecord] = []
        aliases: list[AliasRecord] = []

        def upsert_entity(
            canonical_name: str,
            entity_type: str,
            *,
            aliases_list: list[str] | None = None,
            source_url: str | None = None,
            metadata: dict[str, Any] | None = None,
        ) -> EntityRecord:
            entity_id = stable_id("entity", canonical_name.lower())
            if entity_id not in entities:
                entities[entity_id] = EntityRecord(
                    entity_id=entity_id,
                    canonical_name=canonical_name,
                    entity_type=entity_type,
                    aliases=[],
                    source_urls=[],
                    metadata=metadata or {},
                )
            entity = entities[entity_id]
            if source_url and source_url not in entity.source_urls:
                entity.source_urls.append(source_url)
            if aliases_list:
                for alias in aliases_list:
                    if alias and alias not in entity.aliases:
                        entity.aliases.append(alias)
            if metadata:
                entity.metadata.update({key: value for key, value in metadata.items() if value is not None})
            return entity

        timeline = [
            NameTimelineEntry(
                entity_id=stable_id("entity", "bukidnon external studies center"),
                canonical_name="Bukidnon External Studies Center",
                aliases=["BESC"],
                valid_from="1982",
                valid_to="1992-04-09",
                status="predecessor",
                source_urls=[TIMELINE_SOURCE_URL],
                source_authority="official_site",
                confidence=0.92,
                notes="Opened in Tandag City in 1982 as the Bukidnon State University extension.",
            ),
            NameTimelineEntry(
                entity_id=stable_id("entity", "surigao del sur polytechnic college"),
                canonical_name="Surigao del Sur Polytechnic College",
                aliases=["SSPC"],
                valid_from="1992-04-10",
                valid_to="1998-04-22",
                status="former_official_name",
                source_urls=[TIMELINE_SOURCE_URL],
                source_authority="official_site",
                confidence=0.95,
                notes="Created by Republic Act No. 7377.",
            ),
            NameTimelineEntry(
                entity_id=stable_id("entity", "surigao del sur polytechnic state college"),
                canonical_name="Surigao del Sur Polytechnic State College",
                aliases=["SSPSC"],
                valid_from="1998-04-23",
                valid_to="2010-02-21",
                status="former_official_name",
                source_urls=[TIMELINE_SOURCE_URL],
                source_authority="official_site",
                confidence=0.95,
                notes="State college status earned by virtue of Republic Act No. 8628.",
            ),
            NameTimelineEntry(
                entity_id=stable_id("entity", "surigao del sur state university"),
                canonical_name="Surigao del Sur State University",
                aliases=["SDSSU"],
                valid_from="2010-02-22",
                valid_to="2021-07-29",
                status="former_official_name",
                source_urls=[TIMELINE_SOURCE_URL],
                source_authority="official_site",
                confidence=0.97,
                notes="Converted by Republic Act No. 9998.",
            ),
            NameTimelineEntry(
                entity_id=stable_id("entity", "north eastern mindanao state university"),
                canonical_name="North Eastern Mindanao State University",
                aliases=["NEMSU"],
                valid_from="2021-07-30",
                valid_to=None,
                status="current_official_name",
                source_urls=[TIMELINE_SOURCE_URL],
                source_authority="official_site",
                confidence=0.98,
                notes="Renamed by Republic Act No. 11584.",
            ),
        ]
        for entry in timeline:
            upsert_entity(
                entry.canonical_name,
                "institution_name",
                aliases_list=entry.aliases,
                source_url=TIMELINE_SOURCE_URL,
                metadata={"status": entry.status, "valid_from": entry.valid_from, "valid_to": entry.valid_to},
            )
            aliases.append(AliasRecord(canonical_name=entry.canonical_name, aliases=entry.aliases, entity_id=entry.entity_id))

        for earlier, later in zip(timeline, timeline[1:]):
            relationships.extend(
                [
                    RelationshipRecord(
                        relationship_id=stable_id("rel", earlier.entity_id, "predecessor_of", later.entity_id),
                        subject_entity_id=earlier.entity_id,
                        predicate="predecessor_of",
                        object_entity_id=later.entity_id,
                        valid_from=earlier.valid_from,
                        valid_to=earlier.valid_to,
                        source_urls=[TIMELINE_SOURCE_URL],
                        confidence=min(earlier.confidence, later.confidence),
                    ),
                    RelationshipRecord(
                        relationship_id=stable_id("rel", earlier.entity_id, "renamed_to", later.entity_id),
                        subject_entity_id=earlier.entity_id,
                        predicate="renamed_to",
                        object_entity_id=later.entity_id,
                        valid_from=later.valid_from,
                        source_urls=[TIMELINE_SOURCE_URL],
                        confidence=min(earlier.confidence, later.confidence),
                    ),
                    RelationshipRecord(
                        relationship_id=stable_id("rel", later.entity_id, "formerly_known_as", earlier.entity_id),
                        subject_entity_id=later.entity_id,
                        predicate="formerly_known_as",
                        object_entity_id=earlier.entity_id,
                        source_urls=[TIMELINE_SOURCE_URL],
                        confidence=min(earlier.confidence, later.confidence),
                    ),
                    RelationshipRecord(
                        relationship_id=stable_id("rel", later.entity_id, "effective_on_date", later.valid_from or "unknown"),
                        subject_entity_id=later.entity_id,
                        predicate="effective_on_date",
                        object_name=later.valid_from,
                        source_urls=[TIMELINE_SOURCE_URL],
                        confidence=later.confidence,
                    ),
                ]
            )

        current_university = upsert_entity(
            "North Eastern Mindanao State University",
            "university",
            aliases_list=["NEMSU", "North Eastern Mindanao State University"],
            source_url=TIMELINE_SOURCE_URL,
            metadata={"current_name_valid_from": "2021-07-30"},
        )
        for campus in CAMPUS_NAMES:
            if any(f"{campus} Campus" in page.cleaned_main_body_text or campus in page.title for page in pages):
                campus_entity = upsert_entity(
                    f"{campus} Campus",
                    "campus",
                    aliases_list=[f"NEMSU {campus} Campus", f"{campus} Campus"],
                    source_url=TIMELINE_SOURCE_URL,
                )
                relationships.append(
                    RelationshipRecord(
                        relationship_id=stable_id("rel", campus_entity.entity_id, "belongs_to", current_university.entity_id),
                        subject_entity_id=campus_entity.entity_id,
                        predicate="belongs_to",
                        object_entity_id=current_university.entity_id,
                        source_urls=[TIMELINE_SOURCE_URL],
                        confidence=0.92,
                    )
                )
        bislig_entity_id = stable_id("entity", "bislig campus")
        if bislig_entity_id in entities:
            relationships.append(
                RelationshipRecord(
                    relationship_id=stable_id("rel", bislig_entity_id, "campus_formerly_known_as", "usep former campus in bislig city"),
                    subject_entity_id=bislig_entity_id,
                    predicate="campus_formerly_known_as",
                    object_name="USEP former campus in Bislig City",
                    valid_from="2018",
                    source_urls=[TIMELINE_SOURCE_URL],
                    confidence=0.55,
                    notes="Derived from the official history page wording; a formal prior campus name is not stated there.",
                )
            )

        for page in pages:
            title = page.title
            lowered_title = title.lower()
            if title.startswith("College of") or title == "Graduate Studies":
                college = upsert_entity(title, "college", source_url=page.url)
                relationships.append(
                    RelationshipRecord(
                        relationship_id=stable_id("rel", college.entity_id, "belongs_to", current_university.entity_id),
                        subject_entity_id=college.entity_id,
                        predicate="belongs_to",
                        object_entity_id=current_university.entity_id,
                        source_urls=[page.url],
                        confidence=0.9,
                    )
                )
            if page.page_type == "office/service" or any(name.lower() in lowered_title for name in OFFICE_NAMES):
                office = upsert_entity(title, "office", source_url=page.url)
                relationships.append(
                    RelationshipRecord(
                        relationship_id=stable_id("rel", office.entity_id, "belongs_to", current_university.entity_id),
                        subject_entity_id=office.entity_id,
                        predicate="belongs_to",
                        object_entity_id=current_university.entity_id,
                        source_urls=[page.url],
                        confidence=0.9,
                    )
                )
            if page.page_type in {"policy/manual", "forms", "external_document", "transparency"}:
                doc = upsert_entity(title, "document", source_url=page.url, metadata={"page_type": page.page_type})
                relationships.append(
                    RelationshipRecord(
                        relationship_id=stable_id("rel", doc.entity_id, "document_belongs_to", page.page_type),
                        subject_entity_id=doc.entity_id,
                        predicate="document_belongs_to",
                        object_name=page.page_type,
                        source_urls=[page.url],
                        confidence=0.85,
                    )
                )
            if page.page_type == "program_catalog":
                self._extract_program_entities(page, upsert_entity, relationships)
            for person_name in self._extract_named_people(page.cleaned_main_body_text):
                upsert_entity(person_name, "official", source_url=page.url)
            for email in self._extract_emails(page.cleaned_main_body_text):
                upsert_entity(email, "contact_channel", source_url=page.url, metadata={"kind": "email"})
            for phone in self._extract_phone_numbers(page.cleaned_main_body_text):
                upsert_entity(phone, "contact_channel", source_url=page.url, metadata={"kind": "phone"})

        for portal_name, portal_url in PORTAL_LINKS.items():
            upsert_entity(
                portal_name,
                "service/portal",
                aliases_list=[portal_name],
                source_url=str(self.config.start_url),
                metadata={"url": portal_url, "public_listing_only": True},
            )

        entity_history = [
            EntityHistoryEntry(
                entity_id=current_university.entity_id,
                canonical_name=current_university.canonical_name,
                history=timeline,
            )
        ]
        alias_rows = aliases + [
            AliasRecord(canonical_name=entity.canonical_name, aliases=entity.aliases, entity_id=entity.entity_id)
            for entity in entities.values()
            if entity.aliases
        ]
        return list(entities.values()), alias_rows, relationships, timeline, entity_history

    def _attach_entities_to_chunks(self, chunks: list[ChunkRecord], entities: list[EntityRecord]) -> list[ChunkRecord]:
        alias_map: dict[str, str] = {}
        for entity in entities:
            alias_map[entity.canonical_name.lower()] = entity.entity_id
            for alias in entity.aliases:
                alias_map[alias.lower()] = entity.entity_id
        for chunk in chunks:
            lowered = chunk.normalized_text.lower()
            matched_ids: list[str] = []
            for alias, entity_id in alias_map.items():
                if alias and alias in lowered and entity_id not in matched_ids:
                    matched_ids.append(entity_id)
                if len(matched_ids) >= 12:
                    break
            chunk.entities = matched_ids
        return chunks

    def _build_qa_eval(self, pages: list[PageRecord], chunks: list[ChunkRecord]) -> list[QaEvalRecord]:
        def page_ids_for(predicate: Any) -> list[str]:
            return [page.page_id for page in pages if predicate(page)]

        def chunk_ids_for(predicate: Any) -> list[str]:
            return [chunk.chunk_id for chunk in chunks if predicate(chunk)]

        def urls_for(predicate: Any) -> list[str]:
            return [page.url for page in pages if predicate(page)]

        return [
            QaEvalRecord(
                question="What is NEMSU’s mission and vision?",
                intent="institutional_identity",
                supporting_page_ids=page_ids_for(lambda page: page.page_type == "about"),
                supporting_chunk_ids=chunk_ids_for(lambda chunk: "vision" in chunk.normalized_text.lower() or "mission" in chunk.normalized_text.lower()),
                supporting_urls=urls_for(lambda page: page.page_type == "about"),
            ),
            QaEvalRecord(
                question="What degree programs are offered?",
                intent="academic_programs",
                supporting_page_ids=page_ids_for(lambda page: page.page_type == "program_catalog"),
                supporting_chunk_ids=chunk_ids_for(lambda chunk: chunk.page_type == "program_catalog"),
                supporting_urls=urls_for(lambda page: page.page_type == "program_catalog"),
            ),
            QaEvalRecord(
                question="What are the undergraduate admission requirements?",
                intent="admissions",
                supporting_page_ids=page_ids_for(lambda page: page.page_type == "admissions"),
                supporting_chunk_ids=chunk_ids_for(lambda chunk: "undergraduate" in chunk.normalized_text.lower()),
                supporting_urls=urls_for(lambda page: page.page_type == "admissions"),
            ),
            QaEvalRecord(
                question="What campuses does NEMSU have?",
                intent="campus_info",
                supporting_page_ids=page_ids_for(lambda page: page.page_type in {"about", "campus_info"}),
                supporting_chunk_ids=chunk_ids_for(lambda chunk: "campus" in chunk.normalized_text.lower()),
                supporting_urls=urls_for(lambda page: page.page_type in {"about", "campus_info"}),
            ),
            QaEvalRecord(
                question="What is the difference between current NEMSU and historical SDSSU references?",
                intent="name_history",
                supporting_page_ids=page_ids_for(lambda page: page.page_type == "about"),
                supporting_chunk_ids=chunk_ids_for(lambda chunk: "sdssu" in chunk.normalized_text.lower() or "surigao del sur state university" in chunk.normalized_text.lower()),
                supporting_urls=urls_for(lambda page: page.page_type == "about"),
            ),
            QaEvalRecord(
                question="What recent official news or announcements are on the website?",
                intent="recent_updates",
                supporting_page_ids=page_ids_for(lambda page: page.page_type in {"news", "announcement", "event"}),
                supporting_chunk_ids=chunk_ids_for(lambda chunk: chunk.page_type in {"news", "announcement", "event"}),
                supporting_urls=urls_for(lambda page: page.page_type in {"news", "announcement", "event"}),
            ),
            QaEvalRecord(
                question="Are there public FOI or transparency-related documents?",
                intent="transparency",
                supporting_page_ids=page_ids_for(lambda page: page.page_type in {"transparency", "policy/manual", "forms"}),
                supporting_chunk_ids=chunk_ids_for(lambda chunk: chunk.page_type in {"transparency", "policy/manual", "forms"}),
                supporting_urls=urls_for(lambda page: page.page_type in {"transparency", "policy/manual", "forms"}),
            ),
            QaEvalRecord(
                question="What jobs or procurement notices are publicly posted?",
                intent="jobs_procurement",
                supporting_page_ids=page_ids_for(lambda page: page.page_type in {"jobs", "procurement"}),
                supporting_chunk_ids=chunk_ids_for(lambda chunk: chunk.page_type in {"jobs", "procurement"}),
                supporting_urls=urls_for(lambda page: page.page_type in {"jobs", "procurement"}),
            ),
        ]

    def _build_report(
        self,
        *,
        crawl_records: list[CrawlRecord],
        document_records: list[DocumentRecord],
        pages: list[PageRecord],
        chunks: list[ChunkRecord],
        duplicates: list[dict[str, str]],
        skipped_pages: list[dict[str, str]],
        taxonomy: dict[str, Any],
    ) -> str:
        duplicate_lines = "\n".join(
            f"- `{item['page_id']}` -> `{item['duplicate_of']}` ({item['reason']})" for item in duplicates[:20]
        ) or "- None"
        skipped_lines = "\n".join(f"- `{item['page_id']}`: {item['reason']}" for item in skipped_pages[:20]) or "- None"
        doc_skips = [record for record in document_records if record.skipped_reason]
        doc_skip_lines = "\n".join(
            f"- `{record.document_url}`: {record.skipped_reason}" for record in doc_skips[:20]
        ) or "- None"
        low_confidence = [page for page in pages if page.extraction_confidence < 0.45]
        low_confidence_lines = "\n".join(f"- `{page.url}` ({page.extraction_confidence:.2f})" for page in low_confidence[:15]) or "- None"
        top_topics = "\n".join(f"- {item['topic']}: {item['count']}" for item in taxonomy["top_topics"][:10]) or "- None"
        return "\n".join(
            [
                "# NEMSU Knowledge Base Report",
                "",
                f"Generated at: {utc_now_iso()}",
                "",
                "## Coverage",
                f"- Total URLs discovered/crawled: {len(crawl_records)}",
                f"- Total useful pages extracted: {len(pages)}",
                f"- Total linked documents ingested: {len([record for record in document_records if not record.skipped_reason])}",
                f"- Total chunks created: {len(chunks)}",
                f"- Duplicate pages removed: {len(duplicates)}",
                "",
                "## Top Inferred Topics",
                top_topics,
                "",
                "## Pages Skipped And Why",
                skipped_lines,
                "",
                "## Linked Documents Skipped",
                doc_skip_lines,
                "",
                "## Duplicate Pages Removed",
                duplicate_lines,
                "",
                "## Extraction Issues",
                low_confidence_lines,
                "",
                "## Limitations",
                "- Some pages use sparse or inconsistent titles, so classification falls back to URL and body-text heuristics.",
                "- Public Box shares may expose folder landing pages rather than directly extractable document text.",
                "- Some time-sensitive pages expose dates only in listing text, not machine-readable metadata.",
                "",
                "## Recommended Next Improvements",
                "- Add targeted parsers for BAC/procurement and transparency sections if those URLs become available on the main site.",
                "- Add a local embedding export step directly into the preferred vector-store schema.",
                "- Add scheduled recrawls so news/jobs/documents stay fresh without rebuilding everything from scratch.",
                "",
                "## NEMSU-specific observations",
                "- Historical university aliases and name changes are preserved as time-aware records rather than flat synonyms.",
                "- The site mixes evergreen institutional pages with dated news/jobs listings, so freshness classification is important for retrieval.",
                "- Official public documents are linked both on the main domain and through public Google Drive shares from the Documents page.",
                "- Restricted academic/service portals such as pre-enrollment, LMS, ERMS, CSMS, DTS, Itinero, ePass, and Memo were intentionally excluded from crawling.",
            ]
        )

    def _extract_program_entities(
        self,
        page: PageRecord,
        upsert_entity: Any,
        relationships: list[RelationshipRecord],
    ) -> None:
        university_id = stable_id("entity", "north eastern mindanao state university")
        for table in page.structured_tables:
            rows = table.get("rows", [])
            heading_path = table.get("heading_path", [])
            college_name = next(
                (heading for heading in reversed(heading_path) if "college" in heading.lower() or "graduate" in heading.lower()),
                None,
            )
            college_entity = None
            if college_name:
                college_entity = upsert_entity(college_name, "college", source_url=page.url)
                relationships.append(
                    RelationshipRecord(
                        relationship_id=stable_id("rel", college_entity.entity_id, "belongs_to", university_id),
                        subject_entity_id=college_entity.entity_id,
                        predicate="belongs_to",
                        object_entity_id=university_id,
                        source_urls=[page.url],
                        confidence=0.9,
                    )
                )
            for row in rows[1:]:
                if not row:
                    continue
                program_name = clean_text_block(row[0])
                if not program_name or "academic program" in program_name.lower() or program_name == "---":
                    continue
                metadata = {"accreditation": row[1] if len(row) > 1 else None}
                program_entity = upsert_entity(program_name, "program", source_url=page.url, metadata=metadata)
                if college_entity:
                    relationships.append(
                        RelationshipRecord(
                            relationship_id=stable_id("rel", program_entity.entity_id, "belongs_to", college_entity.entity_id),
                            subject_entity_id=program_entity.entity_id,
                            predicate="belongs_to",
                            object_entity_id=college_entity.entity_id,
                            source_urls=[page.url],
                            confidence=0.88,
                        )
                    )

    def _extract_named_people(self, text: str) -> list[str]:
        import re

        return list(
            dict.fromkeys(
                re.findall(r"\b(?:Dr\.|Atty\.|Engr\.)\s+[A-Z][A-Za-z.-]+(?:\s+[A-Z][A-Za-z.-]+){1,3}", text or "")
            )
        )

    def _extract_emails(self, text: str) -> list[str]:
        import re

        return list(dict.fromkeys(re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text or "")))

    def _extract_phone_numbers(self, text: str) -> list[str]:
        import re

        return list(dict.fromkeys(re.findall(r"\b\d{2,4}-\d{3}-\d{4}\b", text or "")))

    def _write_outputs(
        self,
        *,
        pages: list[PageRecord],
        chunks: list[ChunkRecord],
        taxonomy: dict[str, Any],
        entities: list[EntityRecord],
        aliases: list[AliasRecord],
        relationships: list[RelationshipRecord],
        qa_eval: list[QaEvalRecord],
        report: str,
        name_timeline: list[NameTimelineEntry],
        entity_history: list[EntityHistoryEntry],
    ) -> None:
        write_jsonl(self.output_root / "pages.jsonl", [page.model_dump(mode="json") for page in pages])
        write_jsonl(self.output_root / "chunks.jsonl", [chunk.model_dump(mode="json") for chunk in chunks])
        dump_json(self.output_root / "taxonomy.json", taxonomy)
        dump_json(self.output_root / "entities.json", [entity.model_dump(mode="json") for entity in entities])
        dump_json(self.output_root / "aliases.json", [alias.model_dump(mode="json") for alias in aliases])
        dump_json(self.output_root / "relationships.json", [rel.model_dump(mode="json") for rel in relationships])
        dump_json(self.output_root / "qa_eval.json", [record.model_dump(mode="json") for record in qa_eval])
        dump_json(self.output_root / "name_timeline.json", [entry.model_dump(mode="json") for entry in name_timeline])
        dump_json(self.output_root / "entity_history.json", [entry.model_dump(mode="json") for entry in entity_history])
        (self.output_root / "report.md").write_text(report, encoding="utf-8")
