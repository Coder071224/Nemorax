"""Knowledge-base prompt builder for the neutral chat service."""

from __future__ import annotations

from pathlib import Path
from threading import RLock


_OUT_OF_SCOPE_MESSAGE = "I'm sorry, I can only help with school-related inquiries about NEMSU."


class KnowledgeBasePromptService:
    def __init__(self, markdown_path: Path, *, max_knowledge_chars: int = 6000) -> None:
        self._markdown_path = markdown_path
        self._max_knowledge_chars = max(1000, max_knowledge_chars)
        self._lock = RLock()
        self._cached_prompt = ""
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

    def _build_prompt(self, knowledge_base: str) -> str:
        trimmed_knowledge_base = knowledge_base.strip()
        if len(trimmed_knowledge_base) > self._max_knowledge_chars:
            trimmed_knowledge_base = (
                trimmed_knowledge_base[: self._max_knowledge_chars].rstrip()
                + "\n\n[Knowledge base truncated for request size safety.]"
            )

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

    def get_system_prompt(self) -> str:
        with self._lock:
            try:
                stat = self._markdown_path.stat()
                mtime_ns = stat.st_mtime_ns
            except OSError as exc:
                self._last_error = str(exc)
                self._cached_prompt = self._cached_prompt or self._fallback_prompt()
                return self._cached_prompt

            if self._cached_prompt and self._cached_mtime_ns == mtime_ns:
                return self._cached_prompt

            try:
                knowledge_base = self._markdown_path.read_text(encoding="utf-8").strip()
            except OSError as exc:
                self._last_error = str(exc)
                self._cached_prompt = self._fallback_prompt()
                self._cached_mtime_ns = mtime_ns
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
