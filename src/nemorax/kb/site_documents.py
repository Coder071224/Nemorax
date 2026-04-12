from __future__ import annotations

import io
import re
from pathlib import Path
from urllib.parse import urlparse

import httpx
import trafilatura
from bs4 import BeautifulSoup
from pypdf import PdfReader

from .models import CrawlConfig, CrawlRecord, DocumentRecord
from .utils import append_jsonl, canonicalize_host, ensure_dir, iter_jsonl, looks_like_document_url, normalize_text_for_match, normalize_url, save_text, sha256_text, stable_id, summarize_text, utc_now_iso


class LinkedDocumentIngestor:
    def __init__(self, config: CrawlConfig) -> None:
        self.config = config
        self.output_dir = Path(config.output_directory)
        self.log_dir = Path(config.log_directory)
        self.documents_path = self.output_dir / "raw" / "documents.jsonl"
        self.files_dir = self.output_dir / "raw" / "documents"
        self.errors_path = self.log_dir / "document_errors.jsonl"
        ensure_dir(self.files_dir)
        ensure_dir(self.log_dir)

    def _iter_candidates(self) -> list[tuple[str, str]]:
        candidates = []
        seen: set[str] = set()
        extra_hosts = {canonicalize_host(item) for item in self.config.optional_document_domains}
        for row in iter_jsonl(self.output_dir / "raw" / "crawl_manifest.jsonl"):
            record = CrawlRecord.model_validate(row)
            for link in record.discovered_links:
                url = normalize_url(link)
                host = canonicalize_host(urlparse(url).netloc)
                if host not in {canonicalize_host(item) for item in self.config.allowed_domains} and host not in extra_hosts:
                    continue
                if host in extra_hosts or looks_like_document_url(url):
                    if url not in seen:
                        seen.add(url)
                        candidates.append((record.final_url, url))
        return candidates

    @staticmethod
    def _drive_download(url: str) -> str:
        match = re.search(r"/file/d/([^/]+)/", url) or re.search(r"[?&]id=([^&]+)", url)
        return f"https://drive.google.com/uc?export=download&id={match.group(1)}" if match else url

    @staticmethod
    def _docs_export(url: str) -> str:
        match = re.search(r"/document/d/([^/]+)/", url)
        if match:
            return f"https://docs.google.com/document/d/{match.group(1)}/export?format=txt"
        match = re.search(r"/spreadsheets/d/([^/]+)/", url)
        if match:
            return f"https://docs.google.com/spreadsheets/d/{match.group(1)}/export?format=csv"
        return url

    @staticmethod
    def _extract_pdf(content: bytes) -> tuple[str, int | None]:
        try:
            reader = PdfReader(io.BytesIO(content))
        except Exception:
            return "", None
        text = "\n\n".join((page.extract_text() or "").strip() for page in reader.pages if (page.extract_text() or "").strip())
        return text, len(reader.pages)

    async def ingest(self) -> dict[str, int]:
        candidates = self._iter_candidates()
        ingested = 0
        async with httpx.AsyncClient(headers={"User-Agent": self.config.user_agent}) as client:
            for source_page_url, document_url in candidates:
                request_url = document_url
                host = canonicalize_host(urlparse(document_url).netloc)
                if host == "drive.google.com":
                    request_url = self._drive_download(document_url)
                elif host == "docs.google.com":
                    request_url = self._docs_export(document_url)
                try:
                    response = await client.get(request_url, follow_redirects=True, timeout=self.config.request_timeout_seconds)
                except Exception as exc:
                    append_jsonl(self.errors_path, {"url": document_url, "error": repr(exc), "timestamp": utc_now_iso()})
                    continue
                if response.status_code >= 400:
                    append_jsonl(self.errors_path, {"url": document_url, "status_code": response.status_code, "timestamp": utc_now_iso()})
                    continue
                final_url = normalize_url(str(response.url))
                content_type = (response.headers.get("content-type") or "").lower()
                text = ""
                page_count = None
                doc_type = "html"
                if "pdf" in content_type or final_url.lower().endswith(".pdf"):
                    doc_type = "pdf"
                    text, page_count = self._extract_pdf(response.content)
                elif "text/plain" in content_type or "csv" in content_type:
                    doc_type = "text"
                    text = response.text
                else:
                    text = trafilatura.extract(response.text, include_links=True, include_tables=True, favor_recall=True) or "\n".join(part.strip() for part in BeautifulSoup(response.text, "lxml").stripped_strings)
                text = text.strip()
                if len(normalize_text_for_match(text)) < 80:
                    continue
                title = Path(urlparse(final_url).path).name or summarize_text(text, max_sentences=1) or "Untitled document"
                doc_id = stable_id("doc", final_url)
                file_path = str((self.files_dir / f"{doc_id}.txt").resolve())
                save_text(file_path, text)
                record = DocumentRecord(
                    doc_id=doc_id,
                    source_page_url=source_page_url,
                    document_url=document_url,
                    final_url=final_url,
                    title=title,
                    document_type_guess=doc_type,
                    content_type=content_type,
                    page_count=page_count,
                    extracted_text=text,
                    extraction_confidence=min(0.95, 0.45 + (0.2 if len(text) > 500 else 0) + (0.15 if "nemsu" in normalize_text_for_match(text) else 0)),
                    file_path=file_path,
                    crawl_timestamp=utc_now_iso(),
                    skipped_reason=None,
                )
                append_jsonl(self.documents_path, record.model_dump(mode="json"))
                ingested += 1
        return {"documents_ingested": ingested, "candidate_count": len(candidates)}
