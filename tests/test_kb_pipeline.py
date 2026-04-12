from __future__ import annotations

import sys
import unittest
from pathlib import Path

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from nemorax.kb.builder import KnowledgeBaseBuilder
from nemorax.kb.chunking import build_chunks
from nemorax.kb.dedupe import deduplicate_pages
from nemorax.kb.extractor import PageExtractor
from nemorax.kb.models import CrawlConfig, DocumentRecord, PageRecord, SectionRecord
from nemorax.kb.utils import normalize_url, sha256_text


class KnowledgeBasePipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = CrawlConfig(
            start_url="https://www.nemsu.edu.ph/",
            allowed_domains=["www.nemsu.edu.ph"],
            optional_document_domains=["drive.google.com"],
            output_directory="kb",
            log_directory="logs",
        )

    def test_url_normalization_removes_fragment_and_tracking(self) -> None:
        normalized = normalize_url(
            "https://www.nemsu.edu.ph/aboutus/?utm_source=fb&fbclid=test#history",
            preserve_query=False,
        )
        self.assertEqual(normalized, "https://www.nemsu.edu.ph/aboutus")

    def test_canonical_dedup_keeps_single_page(self) -> None:
        text = "North Eastern Mindanao State University mission and vision."
        page_a = PageRecord(
            page_id="page_a",
            url="https://www.nemsu.edu.ph/aboutus",
            canonical_url="https://www.nemsu.edu.ph/aboutus",
            title="About Us",
            meta_description=None,
            page_type="about",
            freshness="evergreen",
            breadcrumb=[],
            headings=[],
            sections=[SectionRecord(heading_path=["About"], text=text, section_id="section_a")],
            cleaned_main_body_text=text,
            structured_tables=[],
            publication_date=None,
            updated_date=None,
            detected_language="en",
            content_hash=sha256_text(text),
            source_domain="www.nemsu.edu.ph",
            crawl_timestamp="2026-04-12T00:00:00+00:00",
            extraction_confidence=0.9,
        )
        page_b = page_a.model_copy(update={"page_id": "page_b", "url": "https://www.nemsu.edu.ph/aboutus/"})
        deduped, duplicates = deduplicate_pages([page_a, page_b])
        self.assertEqual(len(deduped), 1)
        self.assertEqual(len(duplicates), 1)

    def test_chunking_preserves_heading_path(self) -> None:
        page = PageRecord(
            page_id="page_programs",
            url="https://www.nemsu.edu.ph/academics/programs",
            canonical_url="https://www.nemsu.edu.ph/academics/programs",
            title="Programs Offered",
            meta_description=None,
            page_type="program_catalog",
            freshness="evergreen",
            breadcrumb=[],
            headings=[],
            sections=[
                SectionRecord(
                    heading_path=["College of Teacher Education"],
                    text=("Bachelor of Secondary Education major in English. " * 80).strip(),
                    section_id="section_programs",
                )
            ],
            cleaned_main_body_text=("Bachelor of Secondary Education major in English. " * 80).strip(),
            structured_tables=[],
            publication_date=None,
            updated_date=None,
            detected_language="en",
            content_hash=sha256_text("programs"),
            source_domain="www.nemsu.edu.ph",
            crawl_timestamp="2026-04-12T00:00:00+00:00",
            extraction_confidence=0.9,
        )
        chunks = build_chunks(page, self.config)
        self.assertTrue(chunks)
        self.assertEqual(chunks[0].heading_path, ["College of Teacher Education"])

    def test_schema_validation_for_document_page_provenance(self) -> None:
        builder = KnowledgeBaseBuilder(self.config, ROOT / "kb")
        document = DocumentRecord(
            doc_id="doc_1",
            source_page_url="https://www.nemsu.edu.ph/documents",
            document_url="https://drive.google.com/file/d/abc/view",
            final_url="https://drive.google.com/file/d/abc",
            title="Medium-Term Development Plan",
            document_type_guess="pdf",
            content_type="application/pdf",
            extracted_text="NEMSU Medium-Term Development Plan 2025-2030",
            extraction_confidence=0.8,
            crawl_timestamp="2026-04-12T00:00:00+00:00",
        )
        page = builder._document_to_page(document)
        self.assertIsNotNone(page)
        self.assertEqual(page.provenance["source_page_url"], "https://www.nemsu.edu.ph/documents")
        self.assertEqual(page.page_type, "external_document")

    def test_date_extraction_for_news_page(self) -> None:
        html = """
        <html lang="en">
          <head><title>News</title></head>
          <body>
            <article>
              <h1>Latest News</h1>
              <p>by: Public Information Office | September 15, 2025</p>
            </article>
          </body>
        </html>
        """
        soup = BeautifulSoup(html, "lxml")
        extractor = PageExtractor()
        published, updated = extractor._extract_dates(soup, soup.get_text(" ", strip=True))
        self.assertTrue(published and published.startswith("2025-09-15"))
        self.assertIsNone(updated)


if __name__ == "__main__":
    unittest.main()
