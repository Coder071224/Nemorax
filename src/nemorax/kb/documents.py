from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

import httpx
import trafilatura
from pypdf import PdfReader

from .models import CrawlConfig, CrawlRecord, DocumentRecord
from .utils import append_jsonl, ensure_directory, looks_like_document_url, normalize_url, stable_id, utc_now_iso

DRIVE_FILE_RE = re.compile(r"drive\.google\.com/file/d/([^/]+)")
DOCS_DOCUMENT_RE = re.compile(r"docs\.google\.com/document/d/([^/]+)")
BOX_SHARE_RE = re.compile(r"app\.box\.com/s/([^/?#]+)")


class LinkedDocumentIngestor:
    def __init__(self, config: CrawlConfig, output_root: Path):
        self.config = config
        self.output_root = output_root
        self.raw_root = ensure_directory(output_root / "raw")
        self.files_root = ensure_directory(self.raw_root / "documents")
        self.manifest_path = self.raw_root / "documents_manifest.jsonl"

    async def ingest(self, crawl_records: list[CrawlRecord], *, resume: bool = True) -> list[DocumentRecord]:
        seen: set[str] = set()
        records: list[DocumentRecord] = []
        if not resume and self.manifest_path.exists():
            self.manifest_path.unlink()
        if resume and self.manifest_path.exists():
            for line in self.manifest_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    try:
                        record = DocumentRecord.model_validate_json(line)
                    except Exception:
                        continue
                    records.append(record)
                    seen.add(self._normalize_document_url(record.document_url))
        async with httpx.AsyncClient(
            follow_redirects=True,
            headers={"User-Agent": self.config.user_agent},
            timeout=self.config.request_timeout_seconds,
        ) as client:
            for crawl_record in crawl_records:
                for link in crawl_record.discovered_links:
                    normalized = self._normalize_document_url(link)
                    if normalized in seen or not self._is_candidate(link):
                        continue
                    seen.add(normalized)
                    record = await self._fetch_document(client, crawl_record.final_url, link)
                    if record is None:
                        continue
                    records.append(record)
                    append_jsonl(self.manifest_path, record.model_dump(mode="json"))
        return records

    def _is_candidate(self, url: str) -> bool:
        parsed = urlparse(url)
        hostname = parsed.netloc.lower()
        if hostname in self.config.allowed_domains and looks_like_document_url(url):
            return True
        return hostname in set(self.config.optional_document_domains) and looks_like_document_url(url)

    def _normalize_document_url(self, url: str) -> str:
        if match := DRIVE_FILE_RE.search(url):
            return f"https://drive.google.com/file/d/{match.group(1)}"
        if match := DOCS_DOCUMENT_RE.search(url):
            return f"https://docs.google.com/document/d/{match.group(1)}"
        if match := BOX_SHARE_RE.search(url):
            return f"https://app.box.com/s/{match.group(1)}"
        return normalize_url(url, preserve_query=False)

    async def _fetch_document(self, client: httpx.AsyncClient, source_page_url: str, document_url: str) -> DocumentRecord | None:
        normalized = self._normalize_document_url(document_url)
        final_fetch_url = self._resolve_fetch_url(normalized)
        try:
            response = await client.get(final_fetch_url)
        except Exception:
            return DocumentRecord(
                doc_id=stable_id("doc", normalized),
                source_page_url=source_page_url,
                document_url=document_url,
                final_url=normalized,
                document_type_guess=self._document_type_guess(normalized, None),
                extraction_confidence=0.0,
                crawl_timestamp=utc_now_iso(),
                skipped_reason="fetch_failed",
            )
        content_type = response.headers.get("content-type", "").split(";")[0].strip().lower() or None
        final_url = self._normalize_document_url(str(response.url))
        document_type_guess = self._document_type_guess(final_url, content_type)
        text = ""
        page_count = None
        file_path = None
        title = self._title_from_headers(response)
        if self._looks_like_login(response.text):
            skipped_reason = "public_access_required"
            confidence = 0.0
        else:
            file_name = f"{stable_id('doc', final_url)}{self._file_extension(final_url, content_type)}"
            file_path = str(self.files_root / file_name)
            Path(file_path).write_bytes(response.content)
            text, page_count = self._extract_text(response.content, content_type, final_url)
            skipped_reason = None if text else "no_extractable_text"
            confidence = self._confidence(text, page_count)
        return DocumentRecord(
            doc_id=stable_id("doc", final_url),
            source_page_url=source_page_url,
            document_url=document_url,
            final_url=final_url,
            title=title or self._fallback_title(final_url),
            document_type_guess=document_type_guess,
            content_type=content_type,
            page_count=page_count,
            extracted_text=text,
            extraction_confidence=confidence,
            file_path=file_path,
            crawl_timestamp=utc_now_iso(),
            skipped_reason=skipped_reason,
        )

    def _resolve_fetch_url(self, url: str) -> str:
        if match := DRIVE_FILE_RE.search(url):
            return f"https://drive.google.com/uc?export=download&id={match.group(1)}"
        if match := DOCS_DOCUMENT_RE.search(url):
            return f"https://docs.google.com/document/d/{match.group(1)}/export?format=txt"
        return url

    def _document_type_guess(self, url: str, content_type: str | None) -> str:
        lower_url = url.lower()
        if (content_type or "").endswith("pdf") or lower_url.endswith(".pdf"):
            return "pdf"
        if "google.com/document/" in lower_url:
            return "google_doc"
        if "google.com" in lower_url:
            return "google_drive"
        if "box.com" in lower_url:
            return "box_share"
        if (content_type or "").startswith("text/html"):
            return "html"
        return "file"

    def _extract_text(self, payload: bytes, content_type: str | None, url: str) -> tuple[str, int | None]:
        lower_url = url.lower()
        is_pdf = (content_type or "").endswith("pdf") or lower_url.endswith(".pdf")
        if is_pdf:
            if payload[:5] == b"%PDF-":
                try:
                    reader = PdfReader(BytesIO(payload))
                    text = "\n".join((page.extract_text() or "") for page in reader.pages)
                    if not self._is_low_quality_text(text):
                        return text.strip(), len(reader.pages)
                except Exception:
                    pass
            header = payload[:512].lower()
            if b"<html" not in header and b"<!doctype" not in header:
                return "", None
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError:
            text = payload.decode("latin-1", errors="ignore")
        if "docs.google.com/document/" in url:
            return text.strip(), None
        extracted = trafilatura.extract(text, include_links=True, include_tables=True, favor_recall=True) or text
        extracted = extracted.strip()
        if self._is_low_quality_text(extracted):
            return "", None
        return extracted, None

    def _file_extension(self, url: str, content_type: str | None) -> str:
        path = urlparse(url).path.lower()
        for suffix in (".pdf", ".doc", ".docx", ".txt", ".html", ".htm"):
            if path.endswith(suffix):
                return suffix
        if (content_type or "").endswith("pdf"):
            return ".pdf"
        if (content_type or "").startswith("text/plain"):
            return ".txt"
        if (content_type or "").startswith("text/html"):
            return ".html"
        return ".bin"

    def _title_from_headers(self, response: httpx.Response) -> str | None:
        disposition = response.headers.get("content-disposition", "")
        match = re.search(r'filename="?([^";]+)', disposition)
        return match.group(1).strip() if match else None

    def _fallback_title(self, url: str) -> str:
        path = urlparse(url).path.rstrip("/").split("/")[-1]
        return path or url

    def _confidence(self, text: str, page_count: int | None) -> float:
        score = 0.2
        if len(text) >= 500:
            score += 0.35
        if len(text) >= 2000:
            score += 0.2
        if page_count:
            score += min(0.2, page_count * 0.02)
        return max(0.05, min(score, 0.98))

    def _looks_like_login(self, text: str) -> bool:
        lowered = text.lower()
        return "sign in" in lowered or "login" in lowered or "access denied" in lowered

    def _is_low_quality_text(self, text: str) -> bool:
        if not text:
            return True
        sample = text[:5000]
        printable = sum(1 for char in sample if char.isprintable())
        whitespace = sum(1 for char in sample if char.isspace())
        alpha = sum(1 for char in sample if char.isalpha())
        if printable / max(1, len(sample)) < 0.85:
            return True
        if alpha / max(1, len(sample)) < 0.20 and whitespace / max(1, len(sample)) < 0.05:
            return True
        return False
