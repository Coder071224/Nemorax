"""Knowledge-base prompt builder for the neutral chat service."""

from __future__ import annotations

from pathlib import Path
from threading import RLock
import re


_OUT_OF_SCOPE_MESSAGE = "I'm sorry, I can only help with school-related inquiries about NEMSU."
_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
_SECTION_SPLIT_PATTERN = re.compile(r"(?=^###?\s)", re.MULTILINE)


class KnowledgeBasePromptService:
    def __init__(self, markdown_path: Path, *, max_knowledge_chars: int = 6000) -> None:
        self._markdown_path = markdown_path
        self._max_knowledge_chars = max(1000, max_knowledge_chars)
        self._lock = RLock()
        self._cached_prompt = ""
        self._cached_markdown = ""
        self._cached_mtime_ns: int | None = None
        self._last_error = ""

    @property
    def out_of_scope_message(self) -> str:
        return _OUT_OF_SCOPE_MESSAGE

    @property
    def source_path(self) -> Path:
        return self._markdown_path

    def _fallback_prompt(self) -> str:
        return (
            "You are Nemis, the school information assistant from Nemorax for "
            "North Eastern Mindanao State University (NEMSU). "
            "Answer only questions about official NEMSU school information. "
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

    def _select_relevant_excerpt(self, knowledge_base: str, query: str | None) -> str:
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
            "You are Nemis, the school information assistant from Nemorax for "
            "North Eastern Mindanao State University (NEMSU).\n\n"
            "SCOPE:\n"
            "- Answer only questions about NEMSU school information and official institutional details found in the knowledge base.\n"
            "- Allowed topics include school procedures, admissions, enrollment, offices, contacts, schedules, campuses, facilities, services, directory information, programs, university history, and other school-related operational or institutional information.\n"
            "- Do not answer academic tutoring requests such as solving problems, explaining lessons, doing homework, writing essays, generating code for assignments, or teaching subject matter.\n"
            "- Do not answer questions unrelated to NEMSU school information.\n\n"
            "OUT-OF-SCOPE RESPONSE:\n"
            f"{_OUT_OF_SCOPE_MESSAGE}\n\n"
            "ANSWERING RULES:\n"
            "1. Use only the knowledge base below.\n"
            "2. If the requested information is not stated in the knowledge base, say that it is not available in the knowledge base.\n"
            "3. Do not invent, guess, infer, or combine facts beyond what is written.\n"
            "4. Be concise, clear, and friendly.\n"
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
            available = self._markdown_path.exists() and bool(self._markdown_path.read_text(encoding="utf-8").strip())
        except OSError as exc:
            available = False
            if not self._last_error:
                self._last_error = str(exc)

        prompt = self.get_system_prompt()
        return {
            "available": available,
            "source_path": str(self._markdown_path),
            "detail": self._last_error or (None if prompt else "Prompt is empty."),
        }
