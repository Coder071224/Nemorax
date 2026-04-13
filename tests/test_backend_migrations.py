from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qsl

import httpx

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from nemorax.backend.core.settings import SupabaseSettings
from nemorax.backend.migrate_kb_to_supabase import import_kb
from nemorax.backend.repositories.supabase_client import SupabasePersistenceClient


class FakeKbSupabaseTransport(httpx.MockTransport):
    def __init__(self) -> None:
        self.tables: dict[str, list[dict[str, object]]] = {
            "kb_pages": [],
            "kb_entities": [],
            "kb_aliases": [],
            "kb_relationships": [],
            "kb_name_timeline": [],
            "kb_faq": [],
            "kb_chunks": [],
        }
        super().__init__(self._handler)

    @staticmethod
    def _request_params(request: httpx.Request) -> dict[str, str]:
        return dict(parse_qsl(request.url.query.decode("utf-8"), keep_blank_values=True))

    def _handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if not path.startswith("/rest/v1/"):
            return httpx.Response(status_code=404, json={"message": "not found"})
        table = path.removeprefix("/rest/v1/")
        if table not in self.tables:
            return httpx.Response(status_code=404, json={"message": "unknown table"})
        if request.method != "POST":
            return httpx.Response(status_code=405, json={"message": "unsupported"})

        params = self._request_params(request)
        payload = json.loads(request.content.decode("utf-8")) if request.content else []
        rows = payload if isinstance(payload, list) else [payload]
        on_conflict = [item.strip() for item in params.get("on_conflict", "").split(",") if item.strip()]
        stored = self.tables[table]
        for row in rows:
            if not isinstance(row, dict):
                continue
            index = next(
                (
                    idx
                    for idx, existing in enumerate(stored)
                    if on_conflict and all(str(existing.get(key)) == str(row.get(key)) for key in on_conflict)
                ),
                None,
            )
            if index is None:
                stored.append(dict(row))
            else:
                stored[index] = {**stored[index], **row}
        return httpx.Response(status_code=201, json=[])


class KbMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self._tempdir.name)
        self.kb_root = self.root / "kb"
        self.data_root = self.root / "data"
        self.kb_root.mkdir()
        self.data_root.mkdir()

        (self.kb_root / "pages.jsonl").write_text(
            json.dumps(
                {
                    "page_id": "page-directory",
                    "url": "https://www.nemsu.edu.ph/directory",
                    "canonical_url": "https://www.nemsu.edu.ph/directory",
                    "title": "Directory",
                    "page_type": "directory",
                    "freshness": "evergreen",
                    "breadcrumb": [],
                    "headings": [],
                    "cleaned_main_body_text": "Admissions Office information",
                    "structured_tables": [],
                    "publication_date": None,
                    "updated_date": None,
                    "detected_language": "en",
                    "content_hash": "page-hash",
                    "source_domain": "www.nemsu.edu.ph",
                    "crawl_timestamp": "2026-04-14T00:00:00+00:00",
                    "extraction_confidence": 0.9,
                    "source_links": [],
                    "duplicate_of": None,
                    "provenance": {},
                }
            )
            + "\n",
            encoding="utf-8",
        )
        (self.kb_root / "chunks.jsonl").write_text(
            json.dumps(
                {
                    "chunk_id": "chunk-directory",
                    "page_id": "page-directory",
                    "url": "https://www.nemsu.edu.ph/directory",
                    "title": "Directory",
                    "heading_path": ["Directory"],
                    "page_type": "directory",
                    "topic": "Directory",
                    "raw_text": "Admissions Office: Main campus administration building.",
                    "normalized_text": "admissions office main campus administration building",
                    "short_summary": "Admissions office location.",
                    "keywords": ["admissions", "office"],
                    "entities": ["entity-nemsu"],
                    "publication_date": None,
                    "updated_date": None,
                    "freshness": "evergreen",
                    "content_hash": "chunk-hash",
                    "previous_chunk_id": None,
                    "next_chunk_id": None,
                    "parent_chunk_id": None,
                    "source_section_id": "section-directory",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        (self.kb_root / "entities.json").write_text(
            json.dumps(
                [
                    {
                        "entity_id": "entity-nemsu",
                        "canonical_name": "North Eastern Mindanao State University",
                        "entity_type": "institution",
                        "description": "The university.",
                        "source_urls": ["https://www.nemsu.edu.ph/aboutus"],
                        "metadata": {"abbreviation": "NEMSU"},
                    }
                ]
            ),
            encoding="utf-8",
        )
        (self.kb_root / "aliases.json").write_text(
            json.dumps(
                [
                    {
                        "entity_id": "entity-nemsu",
                        "canonical_name": "North Eastern Mindanao State University",
                        "aliases": ["NEMSU", "SDSSU"],
                    }
                ]
            ),
            encoding="utf-8",
        )
        (self.kb_root / "relationships.json").write_text(
            json.dumps(
                [
                    {
                        "relationship_id": "rel-president",
                        "subject_entity_id": "entity-nemsu",
                        "predicate": "has_president",
                        "object_entity_id": None,
                        "object_name": "Dr. Sample",
                        "valid_from": "2024",
                        "valid_to": None,
                        "source_urls": ["https://www.nemsu.edu.ph/aboutus"],
                        "confidence": 0.9,
                        "notes": None,
                    }
                ]
            ),
            encoding="utf-8",
        )
        (self.kb_root / "name_timeline.json").write_text(
            json.dumps(
                [
                    {
                        "entity_id": "entity-nemsu",
                        "canonical_name": "North Eastern Mindanao State University",
                        "aliases": ["NEMSU"],
                        "valid_from": "2021-07-30",
                        "valid_to": None,
                        "status": "current_official_name",
                        "source_urls": ["https://www.nemsu.edu.ph/aboutus"],
                        "source_authority": "official_site",
                        "confidence": 0.98,
                        "notes": "Renamed by law.",
                    }
                ]
            ),
            encoding="utf-8",
        )
        (self.data_root / "school_info.json").write_text(
            json.dumps(
                {
                    "history": {"current_president": "Dr. Sample"},
                    "faq": [
                        {
                            "question": "What programs does Bislig Campus offer?",
                            "answer": "BS Mechanical Engineering.",
                            "campus": "Bislig",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self._tempdir.cleanup()

    def test_import_kb_moves_runtime_records_to_supabase(self) -> None:
        transport = FakeKbSupabaseTransport()
        client = SupabasePersistenceClient(
            SupabaseSettings(
                url="https://stub-supabase.local",
                anon_key="anon",
                service_role_key="service-role",
                kb_source="supabase",
                timeout_seconds=5.0,
            ),
            transport=transport,
        )

        import nemorax.backend.migrate_kb_to_supabase as module

        original_settings = module.settings
        original_client = module.SupabasePersistenceClient
        try:
            module.settings = type(
                "StubSettings",
                (),
                {
                    "supabase": SupabaseSettings(
                        url="https://stub-supabase.local",
                        anon_key="anon",
                        service_role_key="service-role",
                        kb_source="supabase",
                        timeout_seconds=5.0,
                    )
                },
            )()
            module.SupabasePersistenceClient = lambda config: client
            counts = import_kb(kb_root=self.kb_root, data_root=self.data_root)
        finally:
            module.settings = original_settings
            module.SupabasePersistenceClient = original_client

        self.assertEqual(counts["pages"], 1)
        self.assertEqual(counts["entities"], 1)
        self.assertEqual(counts["aliases"], 2)
        self.assertEqual(counts["relationships"], 1)
        self.assertEqual(counts["timeline_rows"], 1)
        self.assertEqual(counts["faq_rows"], 1)
        self.assertEqual(counts["chunks"], 4)
        self.assertEqual(len(transport.tables["kb_pages"]), 1)
        self.assertEqual(len(transport.tables["kb_entities"]), 1)
        self.assertEqual(len(transport.tables["kb_aliases"]), 2)
        self.assertEqual(len(transport.tables["kb_relationships"]), 1)
        self.assertEqual(len(transport.tables["kb_name_timeline"]), 1)
        self.assertEqual(len(transport.tables["kb_faq"]), 1)
        self.assertEqual(len(transport.tables["kb_chunks"]), 4)


if __name__ == "__main__":
    unittest.main()
