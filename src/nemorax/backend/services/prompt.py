"""Knowledge-base prompt builder for the neutral chat service."""

from __future__ import annotations

import json
from pathlib import Path
from threading import RLock
import re
from typing import Any


_OUT_OF_SCOPE_MESSAGE = "I'm sorry, I can only help with school-related inquiries about NEMSU."
_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
_SECTION_SPLIT_PATTERN = re.compile(r"(?=^###?\s)", re.MULTILINE)


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
        self._max_knowledge_chars = max(1000, max_knowledge_chars)
        self._lock = RLock()
        self._cached_prompt = ""
        self._cached_markdown = ""
        self._cached_mtime_ns: int | None = None
        self._cached_chunks: list[dict[str, Any]] = []
        self._cached_chunks_mtime_ns: int | None = None
        self._last_error = ""

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
        tokens = {token for token in _TOKEN_PATTERN.findall(text.lower()) if len(token) >= 3}
        expanded = set(tokens)
        if "cite" in tokens:
            expanded.update({"college", "information", "technology", "education", "it"})
        if "it" in tokens:
            expanded.update({"information", "technology", "education"})
        if "nemsu" in tokens:
            expanded.add("north")
            expanded.add("eastern")
            expanded.add("mindanao")
            expanded.add("state")
            expanded.add("university")
        return expanded

    def _split_sections(self, knowledge_base: str) -> list[str]:
        sections = [section.strip() for section in _SECTION_SPLIT_PATTERN.split(knowledge_base) if section.strip()]
        return sections or [knowledge_base.strip()]

    def _load_chunks(self) -> tuple[list[dict[str, Any]], int | None]:
        if self._chunks_path is None:
            return [], None

        try:
            stat = self._chunks_path.stat()
            mtime_ns = stat.st_mtime_ns
        except OSError:
            return [], None

        if self._cached_chunks and self._cached_chunks_mtime_ns == mtime_ns:
            return self._cached_chunks, mtime_ns

        chunks: list[dict[str, Any]] = []
        try:
            with self._chunks_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(record, dict):
                        continue
                    text = str(record.get("normalized_text") or record.get("raw_text") or "").strip()
                    if not text:
                        continue
                    record["_token_set"] = self._normalize_tokens(
                        " ".join(
                            [
                                str(record.get("title") or ""),
                                " ".join(record.get("heading_path") or []),
                                " ".join(record.get("keywords") or []),
                                str(record.get("topic") or ""),
                                str(record.get("page_type") or ""),
                                text,
                            ]
                        )
                    )
                    chunks.append(record)
        except OSError as exc:
            self._last_error = str(exc)
            return [], mtime_ns

        self._cached_chunks = chunks
        self._cached_chunks_mtime_ns = mtime_ns
        return chunks, mtime_ns

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
            "what was nemsu called",
        )
        return any(marker in lowered for marker in markers)

    def _is_low_quality_chunk(self, chunk: dict[str, Any]) -> bool:
        text = str(chunk.get("raw_text") or chunk.get("normalized_text") or "")
        lowered = text.lower()
        url = str(chunk.get("url") or "").lower()

        if lowered.startswith("%pdf-"):
            return True
        if "endobj" in lowered and "stream" in lowered:
            return True
        if "drive.usercontent.google.com" in url and "%pdf-" in lowered[:120]:
            return True
        return False

    def _score_chunk(self, chunk: dict[str, Any], query: str, query_tokens: set[str]) -> float:
        token_set = chunk.get("_token_set") or set()
        if not isinstance(token_set, set):
            token_set = set()
        text = str(chunk.get("normalized_text") or chunk.get("raw_text") or "").lower()
        title_tokens = self._normalize_tokens(str(chunk.get("title") or ""))
        heading_tokens = self._normalize_tokens(" ".join(chunk.get("heading_path") or []))
        keyword_tokens = self._normalize_tokens(" ".join(chunk.get("keywords") or []))
        topic_tokens = self._normalize_tokens(str(chunk.get("topic") or ""))

        overlap = len(query_tokens & token_set)
        title_overlap = len(query_tokens & title_tokens)
        heading_overlap = len(query_tokens & heading_tokens)
        keyword_overlap = len(query_tokens & keyword_tokens)
        topic_overlap = len(query_tokens & topic_tokens)

        score = float(overlap + (title_overlap * 4) + (heading_overlap * 3) + (keyword_overlap * 2) + (topic_overlap * 2))

        lowered_query = query.lower().strip()
        if lowered_query and lowered_query in text:
            score += 8.0

        if self._is_low_quality_chunk(chunk):
            score -= 12.0

        if self._query_prefers_time_sensitive(query):
            if chunk.get("freshness") == "time-sensitive":
                score += 3.0
        else:
            if chunk.get("freshness") == "evergreen":
                score += 1.5
            if chunk.get("page_type") in {"directory", "admissions", "about", "campus_info", "program_catalog"}:
                score += 1.0

        if self._query_prefers_history(query):
            if chunk.get("page_type") == "about":
                score += 5.0
            if str(chunk.get("topic") or "").lower() == "history":
                score += 5.0
            if any(marker in text for marker in ("formerly known", "renaming", "renamed", "surigao del sur state university", "surigao del sur polytechnic", "bukidnon external studies center")):
                score += 10.0
            if chunk.get("page_type") in {"news", "announcement", "event"}:
                score -= 6.0

        if "directory" not in lowered_query and chunk.get("page_type") == "external_document":
            score -= 1.5

        return score

    def _format_chunk(self, chunk: dict[str, Any], *, max_chars: int) -> str:
        heading_path = " > ".join(str(item) for item in (chunk.get("heading_path") or []) if item)
        metadata = [
            f"Title: {str(chunk.get('title') or 'Untitled')}",
            f"URL: {str(chunk.get('url') or 'Unknown')}",
        ]
        if heading_path:
            metadata.append(f"Section: {heading_path}")
        page_type = str(chunk.get("page_type") or "").strip()
        if page_type:
            metadata.append(f"Type: {page_type}")
        freshness = str(chunk.get("freshness") or "").strip()
        if freshness:
            metadata.append(f"Freshness: {freshness}")
        publication_date = str(chunk.get("publication_date") or chunk.get("updated_date") or "").strip()
        if publication_date:
            metadata.append(f"Date: {publication_date}")

        body = str(chunk.get("raw_text") or chunk.get("normalized_text") or "").strip()
        if len(body) > max_chars:
            body = body[:max_chars].rstrip() + "..."
        return "\n".join(metadata + ["Content:", body])

    def _select_relevant_chunks_excerpt(self, query: str | None) -> str:
        chunks, _ = self._load_chunks()
        if not chunks:
            return ""

        query_text = (query or "").strip()
        budget = max(1200, self._max_knowledge_chars - 64)
        if not query_text:
            fallback_chunks = [
                chunk for chunk in chunks
                if str(chunk.get("freshness") or "") == "evergreen"
            ] or chunks
            selected = fallback_chunks[:3]
        else:
            query_tokens = self._normalize_tokens(query_text)
            if self._query_prefers_history(query_text):
                query_tokens.update(
                    {
                        "history",
                        "formerly",
                        "renamed",
                        "previous",
                        "alias",
                        "sdssu",
                        "sspsc",
                        "sspc",
                        "besc",
                        "bukidnon",
                        "surigao",
                        "polytechnic",
                    }
                )
            ranked = [
                (self._score_chunk(chunk, query_text, query_tokens), index, chunk)
                for index, chunk in enumerate(chunks)
            ]
            ranked = [item for item in ranked if item[0] > 0]
            if not ranked:
                return ""
            ranked.sort(key=lambda item: (item[0], -item[1]), reverse=True)
            selected = [chunk for _, _, chunk in ranked[:6]]

        selected_blocks: list[str] = []
        total_chars = 0
        per_chunk_budget = max(500, min(1500, budget // max(1, len(selected))))

        for chunk in selected:
            block = self._format_chunk(chunk, max_chars=per_chunk_budget)
            addition = ("\n\n" if selected_blocks else "") + block
            if total_chars and total_chars + len(addition) > budget:
                continue
            if not total_chars and len(block) > budget:
                selected_blocks.append(block[:budget].rstrip())
                total_chars = len(selected_blocks[0])
                break
            selected_blocks.append(block)
            total_chars += len(addition)
            if total_chars >= budget:
                break

        if not selected_blocks:
            return ""

        excerpt = "\n\n".join(selected_blocks).strip()
        if len(selected) < len(chunks):
            excerpt += "\n\n[Knowledge base chunks selected for this request.]"
        return excerpt

    def _select_relevant_excerpt(self, knowledge_base: str, query: str | None) -> str:
        chunk_excerpt = self._select_relevant_chunks_excerpt(query)
        if chunk_excerpt:
            return chunk_excerpt

        trimmed_knowledge_base = knowledge_base.strip()
        if not trimmed_knowledge_base:
            return ""

        if len(trimmed_knowledge_base) <= self._max_knowledge_chars:
            return trimmed_knowledge_base

        if not query or not query.strip():
            return (
                trimmed_knowledge_base[: self._max_knowledge_chars].rstrip()
                + "\n\n[Knowledge base truncated for request size safety.]"
            )

        query_tokens = self._normalize_tokens(query)
        if not query_tokens:
            return (
                trimmed_knowledge_base[: self._max_knowledge_chars].rstrip()
                + "\n\n[Knowledge base truncated for request size safety.]"
            )

        ranked_sections: list[tuple[int, int, str]] = []
        for index, section in enumerate(self._split_sections(trimmed_knowledge_base)):
            section_tokens = self._normalize_tokens(section)
            overlap = len(query_tokens & section_tokens)
            if overlap:
                ranked_sections.append((overlap, -index, section))

        if not ranked_sections:
            return (
                trimmed_knowledge_base[: self._max_knowledge_chars].rstrip()
                + "\n\n[Knowledge base truncated for request size safety.]"
            )

        ranked_sections.sort(reverse=True)
        selected_sections: list[str] = []
        total_chars = 0
        budget = max(1200, self._max_knowledge_chars - 64)

        for _, _, section in ranked_sections:
            addition = ("\n\n" if selected_sections else "") + section
            if total_chars and total_chars + len(addition) > budget:
                continue
            if not total_chars and len(section) > budget:
                selected_sections.append(section[:budget].rstrip())
                total_chars = len(selected_sections[0])
                break
            selected_sections.append(section)
            total_chars += len(addition)
            if total_chars >= budget:
                break

        if not selected_sections:
            return (
                trimmed_knowledge_base[: self._max_knowledge_chars].rstrip()
                + "\n\n[Knowledge base truncated for request size safety.]"
            )

        excerpt = "\n\n".join(selected_sections).strip()
        if len(excerpt) < len(trimmed_knowledge_base):
            excerpt += "\n\n[Knowledge base excerpt selected for this request.]"
        return excerpt

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
            "- Allowed topics include procedures, admissions, enrollment, offices, contacts, schedules, campuses, facilities, services, directory information, programs, university history, and related institutional information.\n"
            "- Do not answer academic tutoring requests such as solving problems, explaining lessons, doing homework, writing essays, generating code for assignments, or teaching subject matter.\n"
            f"- If the user asks for something outside NEMSU school information, reply exactly: {_OUT_OF_SCOPE_MESSAGE}\n\n"
            "Source priority:\n"
            "- First use the Nemorax knowledge base below.\n"
            "- If the app provides relevant data, treat that as authoritative alongside the knowledge base.\n"
            "- If website data is available in the provided context, use it before model background knowledge.\n"
            "- If the answer is not stated in the provided knowledge base or app context, you may use limited general knowledge only when it stays within NEMSU-related school information and you clearly label it as general knowledge that may be incomplete.\n"
            "- If neither the provided data nor reliable general knowledge is enough, say what is missing or uncertain instead of guessing.\n"
            "- Do not override provided KB or app data with general model knowledge.\n\n"
            "Answering rules:\n"
            "1. Base the answer on the provided knowledge base first.\n"
            "2. If the requested information is not stated in the provided knowledge base, say that it is not available in the knowledge base and then use limited general knowledge only if it is clearly relevant and uncertain parts are labeled.\n"
            "3. If partial information exists, answer only that part and state the limitation clearly.\n"
            "4. Do not invent, guess, or present uncertain information as confirmed fact.\n"
            "5. If a user asks for academic help or anything outside school information, reply exactly with the out-of-scope response above.\n\n"
            "KNOWLEDGE BASE:\n"
            f"{trimmed_knowledge_base}\n"
        )

    def _load_markdown(self) -> tuple[str, int | None]:
        try:
            stat = self._markdown_path.stat()
            mtime_ns = stat.st_mtime_ns
        except OSError as exc:
            self._last_error = str(exc)
            return "", None

        if self._cached_markdown and self._cached_mtime_ns == mtime_ns:
            return self._cached_markdown, mtime_ns

        try:
            knowledge_base = self._markdown_path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            self._last_error = str(exc)
            return "", mtime_ns

        self._cached_markdown = knowledge_base
        self._cached_mtime_ns = mtime_ns
        return knowledge_base, mtime_ns

    def get_system_prompt(self) -> str:
        with self._lock:
            knowledge_base, mtime_ns = self._load_markdown()
            if not mtime_ns:
                self._cached_prompt = self._cached_prompt or self._fallback_prompt()
                return self._cached_prompt

            if self._cached_prompt and not self._last_error and self._cached_mtime_ns == mtime_ns:
                return self._cached_prompt

            if not knowledge_base:
                self._last_error = "Knowledge base markdown file is empty."
                self._cached_prompt = self._fallback_prompt()
                self._cached_mtime_ns = mtime_ns
                return self._cached_prompt

            self._last_error = ""
            self._cached_prompt = self._build_prompt(knowledge_base)
            self._cached_mtime_ns = mtime_ns
            return self._cached_prompt

    def get_system_prompt_for_query(self, query: str | None) -> str:
        with self._lock:
            knowledge_base, mtime_ns = self._load_markdown()
            if not mtime_ns:
                return self._cached_prompt or self._fallback_prompt()
            if not knowledge_base:
                self._last_error = "Knowledge base markdown file is empty."
                return self._fallback_prompt()
            self._last_error = ""
            return self._build_prompt(knowledge_base, query)

    def health(self) -> dict[str, str | bool | None]:
        try:
            markdown_available = self._markdown_path.exists() and bool(self._markdown_path.read_text(encoding="utf-8").strip())
        except OSError as exc:
            markdown_available = False
            if not self._last_error:
                self._last_error = str(exc)

        chunks_available = False
        if self._chunks_path is not None:
            try:
                chunks_available = self._chunks_path.exists() and self._chunks_path.stat().st_size > 0
            except OSError as exc:
                if not self._last_error:
                    self._last_error = str(exc)

        prompt = self.get_system_prompt()
        return {
            "available": markdown_available or chunks_available,
            "source_path": str(self._chunks_path or self._markdown_path),
            "markdown_path": str(self._markdown_path),
            "chunks_path": str(self._chunks_path) if self._chunks_path else None,
            "markdown_available": markdown_available,
            "chunks_available": chunks_available,
            "detail": self._last_error or (None if prompt else "Prompt is empty."),
        }
