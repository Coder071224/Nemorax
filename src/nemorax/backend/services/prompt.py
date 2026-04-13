"""Knowledge-base prompt builder for the neutral chat service."""

from __future__ import annotations

import csv
import html
import json
import re
from pathlib import Path
from threading import RLock
from typing import Any

from nemorax.backend.core.logging import get_logger
from nemorax.backend.services.rag import format_context, health as rag_health, retrieve


logger = get_logger("nemorax.prompt")

_OUT_OF_SCOPE_MESSAGE = "I'm sorry, I can only help with school-related inquiries about NEMSU."
_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
_SENTENCE_BOUNDARY_PATTERN = re.compile(r"(?<=[.!?])\s+")
_SECTION_SPLIT_PATTERN = re.compile(r"\n\s*\n+")
_TAG_PATTERN = re.compile(r"<[^>]+>")
_SKIP_DIR_NAMES = {".venv", "venv", "__pycache__", "build", "dist", "website-dist", ".git", "logs"}
_SKIP_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".exe",
    ".apk",
    ".dll",
    ".so",
    ".dylib",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".svg",
    ".bin",
    ".pdf",
}
_SUPPORTED_SUFFIXES = {".txt", ".md", ".json", ".csv", ".jsonl", ".html", ".htm"}
_SKIP_FILE_NAMES = {"embeddings_ready.json", "qa_eval.json", "validation_summary.json"}
_TARGET_CHUNK_TOKENS = 650
_MIN_CHUNK_TOKENS = 400
_MAX_CHUNK_TOKENS = 800
_CHUNK_OVERLAP_TOKENS = 90
_MAX_RETRIEVED_CHUNKS = 6
_STOP_TOKENS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "before",
    "by",
    "called",
    "current",
    "does",
    "for",
    "from",
    "how",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "the",
    "to",
    "was",
    "what",
    "when",
    "where",
    "which",
    "who",
}


class KnowledgeBasePromptService:
    def __init__(
        self,
        markdown_path: Path,
        *,
        chunks_path: Path | None = None,
        max_knowledge_chars: int = 6000,
    ) -> None:
        self._markdown_path = markdown_path
        self._chunks_path = chunks_path
        self._data_root = markdown_path.parent
        self._kb_root = chunks_path.parent if chunks_path is not None else markdown_path.parents[1] / "kb"
        self._max_knowledge_chars = max(1000, max_knowledge_chars)
        self._lock = RLock()
        self._cached_prompt = ""
        self._cached_markdown = ""
        self._cached_markdown_mtime_ns: int | None = None
        self._cached_documents: list[dict[str, Any]] = []
        self._cached_chunks: list[dict[str, Any]] = []
        self._cached_alias_map: dict[str, set[str]] = {}
        self._cached_file_fingerprints: dict[str, int] = {}
        self._last_error = ""
        self._last_retrieval_summary = ""

    @property
    def out_of_scope_message(self) -> str:
        return _OUT_OF_SCOPE_MESSAGE

    @property
    def source_path(self) -> Path:
        return self._chunks_path or self._markdown_path

    def _fallback_prompt(self) -> str:
        return (
            "You are Nemis, the assistant inside the Nemorax app for "
            "North Eastern Mindanao State University (NEMSU). "
            "Answer only school-related questions about NEMSU. "
            "Use plain text and do not use the asterisk character in normal replies. "
            f"If asked anything outside school information, reply exactly: {_OUT_OF_SCOPE_MESSAGE}"
        )

    def _normalize_tokens(self, text: str) -> set[str]:
        tokens = {
            token
            for token in _TOKEN_PATTERN.findall((text or "").lower())
            if len(token) >= 2 and token not in _STOP_TOKENS
        }
        expanded = set(tokens)
        if "cite" in tokens:
            expanded.update({"college", "information", "technology", "education", "it"})
        if "it" in tokens:
            expanded.update({"information", "technology", "education"})
        if "nemsu" in tokens:
            expanded.update({"north", "eastern", "mindanao", "state", "university"})
        if "president" in tokens:
            expanded.update({"university", "head", "leader", "loayon", "designation"})
        return expanded

    def _approx_token_count(self, text: str) -> int:
        return len(_TOKEN_PATTERN.findall(text or ""))

    def _relative_source(self, path: Path) -> str:
        for root in (self._kb_root.parent, self._kb_root, self._data_root):
            try:
                return path.resolve().relative_to(root.resolve()).as_posix()
            except ValueError:
                continue
        return path.as_posix()

    def _normalize_text(self, text: str) -> str:
        return re.sub(r"\s+", " ", (text or "")).strip()

    def _flatten_json_value(
        self,
        value: Any,
        *,
        key_path: tuple[str, ...] = (),
        lines: list[str] | None = None,
        alias_map: dict[str, set[str]] | None = None,
    ) -> list[str]:
        target_lines = lines if lines is not None else []
        if isinstance(value, dict):
            canonical = value.get("canonical_name") or value.get("name") or value.get("title")
            aliases = value.get("aliases")
            if alias_map is not None and isinstance(canonical, str) and canonical.strip():
                group = alias_map.setdefault(canonical.strip().lower(), set())
                group.add(canonical.strip())
                if isinstance(aliases, list):
                    for item in aliases:
                        if isinstance(item, str) and item.strip():
                            group.add(item.strip())
            for key, item in value.items():
                if item in (None, "", [], {}):
                    continue
                self._flatten_json_value(
                    item,
                    key_path=key_path + (str(key),),
                    lines=target_lines,
                    alias_map=alias_map,
                )
            return target_lines

        if isinstance(value, list):
            if value and all(not isinstance(item, (dict, list)) for item in value):
                joined = ", ".join(str(item).strip() for item in value if str(item).strip())
                if joined:
                    label = " > ".join(key_path) if key_path else "value"
                    target_lines.append(f"{label}: {joined}")
                return target_lines
            for index, item in enumerate(value, start=1):
                self._flatten_json_value(
                    item,
                    key_path=key_path + (f"item_{index}",),
                    lines=target_lines,
                    alias_map=alias_map,
                )
            return target_lines

        text = str(value).strip()
        if not text:
            return target_lines
        label = " > ".join(key_path) if key_path else "value"
        target_lines.append(f"{label}: {text}")
        return target_lines

    def _extract_json_metadata(self, payload: Any, path: Path) -> dict[str, Any]:
        metadata: dict[str, Any] = {"title": path.stem.replace("_", " ").strip().title()}
        if isinstance(payload, dict):
            for key in ("title", "name", "canonical_name"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    metadata["title"] = value.strip()
                    break
            for key in ("date", "updated_date", "publication_date", "valid_from"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    metadata["date"] = value.strip()
                    break
        return metadata

    def _build_json_document(
        self,
        *,
        path: Path,
        payload: Any,
        content: str,
        section: str | None = None,
    ) -> dict[str, Any]:
        metadata = self._extract_json_metadata(payload, path)
        if section:
            metadata["section"] = section
        return {
            "source": self._relative_source(path),
            "content": content,
            "type": path.suffix.lstrip("."),
            "metadata": metadata,
        }

    def _read_structured_json(self, path: Path, alias_map: dict[str, set[str]]) -> list[dict[str, Any]]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except json.JSONDecodeError as exc:
            logger.warning("Malformed JSON knowledge file skipped: %s (%s)", path.as_posix(), exc)
            self._last_error = f"Malformed JSON in {path.as_posix()}: {exc}"
            return []
        except OSError as exc:
            logger.warning("Unable to read JSON knowledge file: %s (%s)", path.as_posix(), exc)
            self._last_error = str(exc)
            return []

        documents: list[dict[str, Any]] = []
        if isinstance(payload, dict):
            for key, value in payload.items():
                lines = self._flatten_json_value(
                    value,
                    key_path=(str(key),),
                    alias_map=alias_map,
                )
                block = "\n".join(lines).strip()
                if block:
                    documents.append(
                        self._build_json_document(
                            path=path,
                            payload=value,
                            content=block,
                            section=str(key).replace("_", " ").strip().title(),
                        )
                    )
        else:
            lines = self._flatten_json_value(payload, alias_map=alias_map)
            content = "\n".join(lines).strip()
            if content:
                documents.append(self._build_json_document(path=path, payload=payload, content=content))
        return documents

    def _read_jsonl_document(self, path: Path, alias_map: dict[str, set[str]]) -> dict[str, Any] | None:
        rows: list[str] = []
        try:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                for line_number, line in enumerate(handle, start=1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError as exc:
                        logger.warning(
                            "Malformed JSONL record skipped: %s:%s (%s)",
                            path.as_posix(),
                            line_number,
                            exc,
                        )
                        continue
                    rows.extend(self._flatten_json_value(payload, alias_map=alias_map))
        except OSError as exc:
            logger.warning("Unable to read JSONL knowledge file: %s (%s)", path.as_posix(), exc)
            self._last_error = str(exc)
            return None

        content = "\n".join(rows).strip()
        if not content:
            return None
        return {
            "source": self._relative_source(path),
            "content": content,
            "type": "jsonl",
            "metadata": {"title": path.stem.replace("_", " ").strip().title()},
        }

    def _read_csv_document(self, path: Path) -> dict[str, Any] | None:
        lines: list[str] = []
        try:
            with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
                reader = csv.DictReader(handle)
                for index, row in enumerate(reader, start=1):
                    values = [f"{key}: {value}" for key, value in row.items() if key and value]
                    if values:
                        lines.append(f"row {index}: " + "; ".join(values))
        except OSError as exc:
            logger.warning("Unable to read CSV knowledge file: %s (%s)", path.as_posix(), exc)
            self._last_error = str(exc)
            return None

        content = "\n".join(lines).strip()
        if not content:
            return None
        return {
            "source": self._relative_source(path),
            "content": content,
            "type": "csv",
            "metadata": {"title": path.stem.replace("_", " ").strip().title()},
        }

    def _read_text_document(self, path: Path) -> dict[str, Any] | None:
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logger.warning("Unable to read text knowledge file: %s (%s)", path.as_posix(), exc)
            self._last_error = str(exc)
            return None

        if path.suffix.lower() in {".html", ".htm"}:
            raw = html.unescape(_TAG_PATTERN.sub(" ", raw))
        content = raw.strip()
        if not content:
            return None
        return {
            "source": self._relative_source(path),
            "content": content,
            "type": path.suffix.lstrip("."),
            "metadata": {"title": path.stem.replace("_", " ").strip().title()},
        }

    def _load_document_from_file(self, path: Path, alias_map: dict[str, set[str]]) -> list[dict[str, Any]]:
        suffix = path.suffix.lower()
        if suffix == ".json":
            return self._read_structured_json(path, alias_map)
        if suffix == ".jsonl":
            document = self._read_jsonl_document(path, alias_map)
            return [document] if document is not None else []
        if suffix == ".csv":
            document = self._read_csv_document(path)
            return [document] if document is not None else []
        document = self._read_text_document(path)
        return [document] if document is not None else []

    def _iter_knowledge_files(self) -> tuple[list[Path], dict[str, int]]:
        files: list[Path] = []
        fingerprints: dict[str, int] = {}
        scanned_roots: list[str] = []

        for root in (self._kb_root, self._data_root):
            if not root.exists():
                logger.warning("Knowledge folder not found: %s", root.as_posix())
                continue
            scanned_roots.append(root.as_posix())
            for path in sorted(root.rglob("*")):
                if not path.is_file():
                    continue
                if any(part in _SKIP_DIR_NAMES for part in path.parts):
                    continue
                if path.name in _SKIP_FILE_NAMES:
                    continue
                if path.suffix.lower() in _SKIP_SUFFIXES:
                    continue
                if path.suffix.lower() not in _SUPPORTED_SUFFIXES:
                    continue
                if self._chunks_path is not None and path.resolve() == self._chunks_path.resolve():
                    continue
                files.append(path)
                try:
                    fingerprints[path.as_posix()] = path.stat().st_mtime_ns
                except OSError:
                    fingerprints[path.as_posix()] = -1

        logger.info("Knowledge scan complete. roots=%s files=%s", ", ".join(scanned_roots) or "none", len(files))
        return files, fingerprints

    def _load_structured_chunks(self, alias_map: dict[str, set[str]]) -> list[dict[str, Any]]:
        if self._chunks_path is None or not self._chunks_path.exists():
            return []

        chunks: list[dict[str, Any]] = []
        try:
            with self._chunks_path.open("r", encoding="utf-8", errors="replace") as handle:
                for line_number, line in enumerate(handle, start=1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError as exc:
                        logger.warning(
                            "Malformed chunk record skipped: %s:%s (%s)",
                            self._chunks_path.as_posix(),
                            line_number,
                            exc,
                        )
                        continue
                    if not isinstance(record, dict):
                        continue
                    body = self._normalize_text(str(record.get("raw_text") or record.get("normalized_text") or ""))
                    if not body:
                        continue
                    title = str(record.get("title") or "Untitled").strip() or "Untitled"
                    aliases = record.get("aliases")
                    if isinstance(aliases, list) and aliases:
                        group = alias_map.setdefault(title.lower(), {title})
                        for item in aliases:
                            if isinstance(item, str) and item.strip():
                                group.add(item.strip())
                    source = self._relative_source(self._chunks_path)
                    metadata = {
                        "title": title,
                        "section": " > ".join(str(item) for item in (record.get("heading_path") or []) if item),
                        "url": str(record.get("url") or "").strip(),
                        "type": str(record.get("page_type") or "").strip(),
                        "date": str(record.get("publication_date") or record.get("updated_date") or "").strip(),
                    }
                    chunks.append(
                        self._finalize_chunk(
                            source=source,
                            content=body,
                            doc_type="jsonl",
                            metadata=metadata,
                        )
                    )
        except OSError as exc:
            logger.warning("Unable to read structured chunks: %s (%s)", self._chunks_path.as_posix(), exc)
            self._last_error = str(exc)
            return []

        logger.info("Structured chunk file loaded. source=%s chunks=%s", self._chunks_path.as_posix(), len(chunks))
        return chunks

    def _split_document_sections(self, text: str) -> list[str]:
        cleaned = text.replace("\r\n", "\n").replace("\r", "\n").strip()
        if not cleaned:
            return []
        sections = [part.strip() for part in _SECTION_SPLIT_PATTERN.split(cleaned) if part.strip()]
        return sections or [cleaned]

    def _chunk_overlap_text(self, text: str) -> str:
        tokens = _TOKEN_PATTERN.findall(text or "")
        if not tokens:
            return ""
        return " ".join(tokens[-_CHUNK_OVERLAP_TOKENS:])

    def _finalize_chunk(
        self,
        *,
        source: str,
        content: str,
        doc_type: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        normalized = self._normalize_text(content)
        token_set = self._normalize_tokens(
            " ".join([normalized, str(metadata.get("title") or ""), str(metadata.get("section") or "")])
        )
        return {
            "source": source,
            "content": normalized,
            "type": doc_type,
            "metadata": metadata,
            "_token_set": token_set,
        }

    def _chunk_document(self, document: dict[str, Any]) -> list[dict[str, Any]]:
        sections = self._split_document_sections(str(document.get("content") or ""))
        if not sections:
            return []

        chunks: list[dict[str, Any]] = []
        buffer: list[str] = []
        current_tokens = 0
        overlap = ""

        for section in sections:
            section_text = self._normalize_text(section)
            if not section_text:
                continue
            section_tokens = self._approx_token_count(section_text)
            sentences = (
                [part.strip() for part in _SENTENCE_BOUNDARY_PATTERN.split(section_text) if part.strip()]
                if section_tokens > _MAX_CHUNK_TOKENS
                else [section_text]
            )

            for sentence in sentences:
                sentence_tokens = self._approx_token_count(sentence)
                if buffer and current_tokens >= _MIN_CHUNK_TOKENS and current_tokens + sentence_tokens > _TARGET_CHUNK_TOKENS:
                    chunk_text = "\n\n".join(buffer).strip()
                    chunks.append(
                        self._finalize_chunk(
                            source=str(document["source"]),
                            content=chunk_text,
                            doc_type=str(document["type"]),
                            metadata=dict(document["metadata"]),
                        )
                    )
                    overlap = self._chunk_overlap_text(chunk_text)
                    buffer = [overlap] if overlap else []
                    current_tokens = self._approx_token_count(overlap)

                buffer.append(sentence)
                current_tokens += sentence_tokens

                if current_tokens >= _MAX_CHUNK_TOKENS:
                    chunk_text = "\n\n".join(buffer).strip()
                    chunks.append(
                        self._finalize_chunk(
                            source=str(document["source"]),
                            content=chunk_text,
                            doc_type=str(document["type"]),
                            metadata=dict(document["metadata"]),
                        )
                    )
                    overlap = self._chunk_overlap_text(chunk_text)
                    buffer = [overlap] if overlap else []
                    current_tokens = self._approx_token_count(overlap)

        if buffer:
            chunk_text = "\n\n".join(buffer).strip()
            chunks.append(
                self._finalize_chunk(
                    source=str(document["source"]),
                    content=chunk_text,
                    doc_type=str(document["type"]),
                    metadata=dict(document["metadata"]),
                )
            )
        return chunks

    def _load_documents_and_chunks(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, set[str]]]:
        knowledge_files, fingerprints = self._iter_knowledge_files()
        if self._cached_documents and self._cached_chunks and self._cached_file_fingerprints == fingerprints:
            return self._cached_documents, self._cached_chunks, self._cached_alias_map

        alias_map: dict[str, set[str]] = {}
        documents: list[dict[str, Any]] = []

        for path in knowledge_files:
            documents.extend(self._load_document_from_file(path, alias_map))

        chunks = self._load_structured_chunks(alias_map)
        for document in documents:
            chunks.extend(self._chunk_document(document))

        self._cached_documents = documents
        self._cached_chunks = chunks
        self._cached_alias_map = alias_map
        self._cached_file_fingerprints = fingerprints

        logger.info(
            "Knowledge load complete. files_loaded=%s docs=%s chunks=%s",
            len(knowledge_files),
            len(documents),
            len(chunks),
        )
        return documents, chunks, alias_map

    def _load_chunks(self) -> tuple[list[dict[str, Any]], int | None]:
        _, chunks, _ = self._load_documents_and_chunks()
        latest_mtime = max(self._cached_file_fingerprints.values(), default=None)
        return chunks, latest_mtime

    def _load_markdown(self) -> tuple[str, int | None]:
        try:
            stat = self._markdown_path.stat()
            mtime_ns = stat.st_mtime_ns
        except OSError as exc:
            self._last_error = str(exc)
            return "", None

        if self._cached_markdown and self._cached_markdown_mtime_ns == mtime_ns:
            return self._cached_markdown, mtime_ns

        try:
            knowledge_base = self._markdown_path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError as exc:
            self._last_error = str(exc)
            return "", mtime_ns

        self._cached_markdown = knowledge_base
        self._cached_markdown_mtime_ns = mtime_ns
        return knowledge_base, mtime_ns

    def _query_prefers_time_sensitive(self, query: str) -> bool:
        lowered = query.lower()
        markers = ("latest", "recent", "today", "current", "new", "news", "announcement", "update")
        return any(marker in lowered for marker in markers)

    def _query_prefers_history(self, query: str) -> bool:
        lowered = query.lower()
        markers = (
            "before",
            "formerly",
            "old name",
            "called before",
            "previous name",
            "used to be",
            "renamed",
            "history",
            "historical name",
            "alias",
        )
        return any(marker in lowered for marker in markers)

    def _query_prefers_identity(self, query: str) -> bool:
        lowered = query.lower().strip()
        markers = (
            "what is nemsu",
            "who is nemsu",
            "what does nemsu stand for",
            "define nemsu",
        )
        return any(marker in lowered for marker in markers)

    def _query_prefers_leadership(self, query: str) -> bool:
        lowered = query.lower()
        markers = (
            "president",
            "university president",
            "head of nemsu",
            "leader of nemsu",
            "who leads nemsu",
        )
        return any(marker in lowered for marker in markers)

    def _query_prefers_programs(self, query: str) -> bool:
        lowered = query.lower()
        markers = (
            "course",
            "courses",
            "program",
            "programs",
            "offered",
            "available",
            "degree",
            "degrees",
            "college offers",
            "campus offers",
        )
        return any(marker in lowered for marker in markers)

    def _expand_query_tokens(self, query: str, alias_map: dict[str, set[str]]) -> tuple[set[str], set[str]]:
        lowered_query = query.lower()
        query_tokens = self._normalize_tokens(query)
        alias_tokens: set[str] = set()
        for group in alias_map.values():
            lowered_group = [item.lower() for item in group if item]
            if any(item and item in lowered_query for item in lowered_group):
                for item in group:
                    alias_tokens.update(self._normalize_tokens(item))
        return query_tokens | alias_tokens, alias_tokens

    def _query_phrases(self, query: str) -> set[str]:
        words = [word for word in re.split(r"\s+", query.lower().strip()) if word]
        phrases: set[str] = set()
        for size in range(2, min(5, len(words)) + 1):
            for index in range(len(words) - size + 1):
                phrase = " ".join(words[index : index + size]).strip()
                if len(phrase) >= 5:
                    phrases.add(phrase)
        return phrases

    def _score_chunk(
        self,
        chunk: dict[str, Any],
        *,
        query: str,
        query_tokens: set[str],
        query_phrases: set[str],
        alias_tokens: set[str],
    ) -> float:
        token_set = chunk.get("_token_set") or set()
        if not isinstance(token_set, set) or not token_set:
            return 0.0

        overlap_ratio = len(query_tokens & token_set) / max(1, len(query_tokens))
        score = overlap_ratio * 10.0
        body = str(chunk.get("content") or "").lower()
        metadata = chunk.get("metadata") or {}
        title_tokens = self._normalize_tokens(str(metadata.get("title") or ""))
        section_tokens = self._normalize_tokens(str(metadata.get("section") or ""))
        type_tokens = self._normalize_tokens(str(chunk.get("type") or metadata.get("type") or ""))

        score += (len(query_tokens & title_tokens) / max(1, len(query_tokens))) * 4.0
        score += (len(query_tokens & section_tokens) / max(1, len(query_tokens))) * 2.5
        score += (len(query_tokens & type_tokens) / max(1, len(query_tokens))) * 1.5
        if alias_tokens:
            score += (len(alias_tokens & token_set) / max(1, len(alias_tokens))) * 4.0

        for phrase in query_phrases:
            if phrase in body:
                score += 3.5 if len(phrase.split()) >= 3 else 2.0

        lowered_query = query.lower().strip()
        if lowered_query and lowered_query in body:
            score += 5.0

        if self._query_prefers_history(query):
            if any(token in body for token in ("formerly", "renamed", "previous name", "current official name", "former official name")):
                score += 4.0
            if "history" in body or "timeline" in body:
                score += 3.0
            if str(metadata.get("title") or "").lower() in {"aliases", "name timeline", "entity history", "school info"}:
                score += 3.0
            if str(metadata.get("section") or "").lower() in {"history", "institution"}:
                score += 2.5
        elif self._query_prefers_leadership(query):
            if any(
                token in body
                for token in (
                    "current president",
                    "university president",
                    "designation: university president",
                    "dr. nemesio g. loayon",
                    "nemesio g. loayon",
                    "op@nemsu.edu.ph",
                )
            ):
                score += 6.0
            if str(metadata.get("section") or "").lower() in {"history", "directory"}:
                score += 3.0
            if "president" in str(metadata.get("section") or "").lower():
                score += 2.0
        elif self._query_prefers_identity(query):
            if any(
                token in body
                for token in (
                    "north eastern mindanao state university",
                    "stands for",
                    "abbreviation",
                    "institution > name",
                )
            ):
                score += 4.0
            if str(metadata.get("title") or "").lower() in {"school info", "aliases"}:
                score += 2.0
            if str(metadata.get("section") or "").lower() == "institution":
                score += 4.0
        elif self._query_prefers_programs(query):
            if any(
                token in body
                for token in (
                    "what programs does",
                    "programs:",
                    "offers graduate and undergraduate programs",
                    "main_campus_programs",
                    "campuses > programs",
                    "college_of_",
                    "bachelor of science",
                    "bachelor of",
                    "master of",
                    "doctor of",
                )
            ):
                score += 5.0
            if str(metadata.get("section") or "").lower() in {"main campus programs", "campuses"}:
                score += 3.0
            if "program" in str(metadata.get("title") or "").lower() or "program" in str(metadata.get("section") or "").lower():
                score += 2.5
        elif self._query_prefers_time_sensitive(query):
            if any(token in body for token in ("current", "present", "as of", "today")):
                score += 2.0

        return score

    def _format_chunk(self, chunk: dict[str, Any], *, max_chars: int) -> str:
        metadata = chunk.get("metadata") or {}
        parts = [f"Source: {chunk.get('source') or 'Unknown'}"]
        title = str(metadata.get("title") or "").strip()
        if title:
            parts.append(f"Title: {title}")
        section = str(metadata.get("section") or "").strip()
        if section:
            parts.append(f"Section: {section}")
        chunk_type = str(metadata.get("type") or chunk.get("type") or "").strip()
        if chunk_type:
            parts.append(f"Type: {chunk_type}")
        date = str(metadata.get("date") or "").strip()
        if date:
            parts.append(f"Date: {date}")
        url = str(metadata.get("url") or "").strip()
        if url:
            parts.append(f"URL: {url}")

        body = self._normalize_text(str(chunk.get("content") or ""))
        if len(body) > max_chars:
            body = body[:max_chars].rstrip() + "..."
        return "[" + " | ".join(parts) + "]\n" + body

    def _select_relevant_chunks_excerpt(self, query: str | None) -> str:
        _, chunks, alias_map = self._load_documents_and_chunks()
        if not chunks:
            logger.warning("Knowledge retrieval fallback triggered: no chunks available.")
            self._last_retrieval_summary = "fallback:no_chunks"
            return ""

        query_text = (query or "").strip()
        if not query_text:
            selected = chunks[: min(3, len(chunks))]
            self._last_retrieval_summary = "fallback:no_query"
        else:
            query_tokens, alias_tokens = self._expand_query_tokens(query_text, alias_map)
            query_phrases = self._query_phrases(query_text)
            ranked: list[tuple[float, int, dict[str, Any]]] = []
            for index, chunk in enumerate(chunks):
                score = self._score_chunk(
                    chunk,
                    query=query_text,
                    query_tokens=query_tokens,
                    query_phrases=query_phrases,
                    alias_tokens=alias_tokens,
                )
                if score > 0:
                    ranked.append((score, index, chunk))

            if not ranked:
                logger.warning("Knowledge retrieval fallback triggered: query=%r had no positive matches.", query_text)
                self._last_retrieval_summary = "fallback:no_positive_matches"
                return ""

            ranked.sort(key=lambda item: (item[0], -item[1]), reverse=True)
            selected = [chunk for _, _, chunk in ranked[:_MAX_RETRIEVED_CHUNKS]]
            logger.info(
                "Top knowledge matches for query=%r -> %s",
                query_text,
                ", ".join(
                    f"{item[2].get('source')} ({item[0]:.2f})"
                    for item in ranked[:_MAX_RETRIEVED_CHUNKS]
                ),
            )
            self._last_retrieval_summary = "ranked"

        budget = max(1200, self._max_knowledge_chars - 96)
        per_chunk_budget = max(500, min(1500, budget // max(1, len(selected))))
        blocks: list[str] = []
        total_chars = 0

        for chunk in selected:
            block = self._format_chunk(chunk, max_chars=per_chunk_budget)
            addition = ("\n\n" if blocks else "") + block
            if total_chars and total_chars + len(addition) > budget:
                continue
            if not total_chars and len(block) > budget:
                blocks.append(block[:budget].rstrip())
                break
            blocks.append(block)
            total_chars += len(addition)
            if total_chars >= budget:
                break

        return "\n\n".join(blocks).strip()

    def _select_relevant_excerpt(self, knowledge_base: str, query: str | None) -> str:
        chunk_excerpt = self._select_relevant_chunks_excerpt(query)
        if chunk_excerpt:
            return chunk_excerpt

        trimmed_knowledge_base = knowledge_base.strip()
        if not trimmed_knowledge_base:
            return ""

        if len(trimmed_knowledge_base) <= self._max_knowledge_chars:
            return trimmed_knowledge_base

        excerpt = trimmed_knowledge_base[: self._max_knowledge_chars].rstrip()
        logger.info("Knowledge retrieval fallback triggered: using markdown excerpt.")
        return excerpt + "\n\n[Knowledge base truncated for request size safety.]"

    def _build_prompt(self, knowledge_base: str, query: str | None = None) -> str:
        trimmed_knowledge_base = self._select_relevant_excerpt(knowledge_base, query)

        return (
            "You are Nemis, the assistant inside the Nemorax app.\n\n"
            "Answer clearly, accurately, and naturally.\n"
            "Prioritize correctness, clarity, and relevance.\n"
            "Use plain text.\n\n"
            "Rules:\n"
            "- Do not use the asterisk character in normal replies.\n"
            "- Do not use markdown emphasis.\n"
            "- Do not wrap words in stars.\n"
            "- Do not use decorative formatting.\n"
            "- Do not roleplay.\n"
            "- Do not use action text.\n"
            "- Do not use filler introductions unless needed.\n"
            "- Do not repeat the user's question.\n"
            "- Do not invent facts.\n\n"
            "Style:\n"
            "- Start with the direct answer.\n"
            "- Then give the necessary explanation.\n"
            "- Keep answers concise unless the user asks for detail.\n"
            "- Be professional, smooth, and human.\n\n"
            "Scope:\n"
            "- Answer only questions about NEMSU school information and official institutional details.\n"
            "- Allowed topics include procedures, admissions, enrollment, offices, contacts, schedules, campuses, facilities, services, directory information, programs, university history, leadership, historical names, aliases, and related institutional information.\n"
            "- Do not answer academic tutoring requests such as solving problems, explaining lessons, doing homework, writing essays, generating code for assignments, or teaching subject matter.\n"
            f"- If the user asks for something outside NEMSU school information, reply exactly: {_OUT_OF_SCOPE_MESSAGE}\n\n"
            "Source priority:\n"
            "- Use the retrieved knowledge context below first.\n"
            "- Treat the retrieved context as authoritative before any model background knowledge.\n"
            "- If the answer is not stated in the retrieved context, say clearly that it is not available in the current knowledge base.\n"
            "- Do not hallucinate missing details.\n"
            "- Do not override provided local KB data with general model knowledge.\n\n"
            "Answering rules:\n"
            "1. Base the answer on the provided retrieved context first.\n"
            "2. If the requested information is not stated in the retrieved context, say that it is not available in the current knowledge base.\n"
            "3. If partial information exists, answer only that part and state the limitation clearly.\n"
            "4. Do not invent, guess, or present uncertain information as confirmed fact.\n"
            "5. If a user asks for academic help or anything outside school information, reply exactly with the out-of-scope response above.\n\n"
            "RETRIEVED KNOWLEDGE CONTEXT:\n"
            f"{trimmed_knowledge_base}\n"
        )

    def _build_semantic_prompt(
        self,
        *,
        query: str | None,
        conversation_history: list[dict[str, str]] | None = None,
    ) -> str:
        service_root = Path(__file__).resolve().parents[4]
        try:
            self._markdown_path.resolve().relative_to(service_root.resolve())
        except ValueError:
            return ""
        context = format_context(retrieve(query or "", conversation_history=conversation_history or []))
        if context:
            return (
                "You are Nemis, the official AI assistant of NEMSU "
                "(Northeastern Mindanao State University). You answer questions about NEMSU "
                "clearly and accurately based on the knowledge provided below.\n\n"
                "IMPORTANT RULES:\n"
                "- Answer ONLY from the provided knowledge context when it contains the answer.\n"
                "- If the answer is clearly in the context, state it directly and confidently.\n"
                "- If the context does not contain enough information, say:\n"
                "\"I don't have that specific information in my knowledge base right now.\n"
                " Please contact the NEMSU office directly for accurate details.\"\n"
                "- Never make up names, dates, or facts not present in the context.\n"
                "- Keep answers concise and helpful.\n"
                "- You may use conversation history to resolve follow-up questions.\n"
                "- Do not use markdown emphasis or asterisks in normal replies.\n\n"
                "RETRIEVED KNOWLEDGE CONTEXT:\n"
                f"{context}"
            )
        return ""

    def get_system_prompt(self) -> str:
        with self._lock:
            self._cached_prompt = self._cached_prompt or self._fallback_prompt()
            return self._cached_prompt

    def get_system_prompt_for_query(
        self,
        query: str | None,
        conversation_history: list[dict[str, str]] | None = None,
    ) -> str:
        with self._lock:
            semantic_prompt = self._build_semantic_prompt(query=query, conversation_history=conversation_history)
            if semantic_prompt:
                return semantic_prompt
            knowledge_base, _ = self._load_markdown()
            self._last_error = ""
            return self._build_prompt(knowledge_base, query)

    def health(self) -> dict[str, str | bool | None | int]:
        rag_status = rag_health()
        try:
            markdown_available = self._markdown_path.exists() and bool(
                self._markdown_path.read_text(encoding="utf-8", errors="replace").strip()
            )
        except OSError as exc:
            markdown_available = False
            if not self._last_error:
                self._last_error = str(exc)

        chunks, _ = self._load_chunks()
        documents = self._cached_documents
        scanned_files = len(self._cached_file_fingerprints)
        chunks_available = bool(chunks)

        prompt = self.get_system_prompt()
        return {
            "available": bool(rag_status.get("available")) or markdown_available or chunks_available,
            "source_path": str(rag_status.get("source_path") or self._chunks_path or self._markdown_path),
            "markdown_path": str(self._markdown_path),
            "chunks_path": str(self._chunks_path) if self._chunks_path else None,
            "markdown_available": markdown_available,
            "chunks_available": chunks_available,
            "documents_loaded": len(documents),
            "files_scanned": scanned_files,
            "chunk_count": len(chunks),
            "detail": rag_status.get("detail") or self._last_error or (None if prompt else "Prompt is empty."),
        }
