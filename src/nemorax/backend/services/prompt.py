"""Knowledge-base prompt builder backed primarily by Supabase."""

from __future__ import annotations

import json
import re
from pathlib import Path
from threading import RLock
from typing import Any

from nemorax.backend.core.logging import get_logger
from nemorax.backend.services.supabase_kb import SupabaseKnowledgeBaseClient


logger = get_logger("nemorax.prompt")

_OUT_OF_SCOPE_MESSAGE = "I'm sorry, I can only help with school-related inquiries about NEMSU."
_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
_STOP_TOKENS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
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
        markdown_path: Path | None = None,
        *,
        chunks_path: Path | None = None,
        max_knowledge_chars: int = 6000,
        kb_source: str = "supabase",
        supabase_client: SupabaseKnowledgeBaseClient | None = None,
    ) -> None:
        self._markdown_path = markdown_path
        self._chunks_path = chunks_path
        self._legacy_json_path = markdown_path.with_suffix(".json") if markdown_path is not None else None
        self._max_knowledge_chars = max(1000, max_knowledge_chars)
        self._kb_source = kb_source.strip().lower() or "supabase"
        self._supabase_client = supabase_client
        self._lock = RLock()
        self._cached_prompt = ""
        self._last_error = ""
        self._last_retrieval_summary = ""
        self._local_chunks_cache: list[dict[str, Any]] | None = None
        self._local_alias_map: dict[str, set[str]] | None = None

    @property
    def out_of_scope_message(self) -> str:
        return _OUT_OF_SCOPE_MESSAGE

    @property
    def source_path(self) -> Path:
        if self._uses_supabase():
            return Path("supabase://kb_chunks")
        return self._chunks_path or self._markdown_path or Path("legacy://kb_unconfigured")

    def _uses_supabase(self) -> bool:
        return bool(self._supabase_client and self._supabase_client.enabled and self._kb_source == "supabase")

    def _fallback_prompt(self) -> str:
        return (
            "You are Nemis, the assistant inside the Nemorax app for "
            "North Eastern Mindanao State University (NEMSU). "
            "You are a scoped campus assistant: warm, natural, and helpful, but limited to NEMSU-related information. "
            "Use plain text and do not use the asterisk character in normal replies. "
            "If a request is outside NEMSU scope, politely redirect the user toward NEMSU topics instead of sounding robotic."
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
        if "cbm" in tokens:
            expanded.update({"college", "business", "management"})
        if "nemsu" in tokens:
            expanded.update({"north", "eastern", "mindanao", "state", "university"})
        if "president" in tokens:
            expanded.update({"leader", "head", "university"})
        return expanded

    def _normalize_text(self, text: str) -> str:
        return re.sub(r"\s+", " ", (text or "")).strip()

    def _relative_source(self, path: Path) -> str:
        if path.name == "chunks.jsonl":
            return f"{path.parent.name}/{path.name}"
        if path.name == "school_info.json":
            return f"{path.parent.name}/{path.name}"
        return path.as_posix()

    def _flatten_json(self, value: Any, *, key_path: tuple[str, ...] = ()) -> list[str]:
        lines: list[str] = []
        if isinstance(value, dict):
            for key, item in value.items():
                if item in (None, "", [], {}):
                    continue
                lines.extend(self._flatten_json(item, key_path=key_path + (str(key),)))
            return lines
        if isinstance(value, list):
            if value and all(not isinstance(item, (dict, list)) for item in value):
                label = " > ".join(key_path) if key_path else "value"
                joined = ", ".join(str(item).strip() for item in value if str(item).strip())
                if joined:
                    lines.append(f"{label}: {joined}")
                return lines
            for index, item in enumerate(value, start=1):
                lines.extend(self._flatten_json(item, key_path=key_path + (f"item_{index}",)))
            return lines
        text = str(value).strip()
        if text:
            label = " > ".join(key_path) if key_path else "value"
            lines.append(f"{label}: {text}")
        return lines

    def _chunk_payload(
        self,
        *,
        source: str,
        content: str,
        metadata: dict[str, Any],
        score: float = 0.0,
    ) -> dict[str, Any]:
        return {
            "source": source,
            "content": content,
            "metadata": metadata,
            "_token_set": self._normalize_tokens(
                " ".join(
                    [
                        content,
                        str(metadata.get("title") or ""),
                        str(metadata.get("section") or ""),
                        str(metadata.get("topic") or ""),
                    ]
                )
            ),
            "_retrieval_score": score,
        }

    def _load_local_legacy_chunks(self) -> tuple[list[dict[str, Any]], dict[str, set[str]]]:
        if self._local_chunks_cache is not None and self._local_alias_map is not None:
            return list(self._local_chunks_cache), dict(self._local_alias_map)

        chunks: list[dict[str, Any]] = []
        alias_map: dict[str, set[str]] = {}

        if self._chunks_path and self._chunks_path.exists():
            try:
                with self._chunks_path.open("r", encoding="utf-8", errors="replace") as handle:
                    for line in handle:
                        raw = line.strip()
                        if not raw:
                            continue
                        payload = json.loads(raw)
                        title = str(payload.get("title") or "").strip()
                        heading_path = payload.get("heading_path") or []
                        url = str(payload.get("url") or "").strip()
                        page_type = str(payload.get("page_type") or "").strip()
                        topic = str(payload.get("topic") or "").strip()
                        content = str(payload.get("raw_text") or payload.get("normalized_text") or "").strip()
                        if not content:
                            continue
                        if title:
                            alias_map.setdefault(title.lower(), {title})
                        chunks.append(
                            self._chunk_payload(
                                source=self._relative_source(self._chunks_path),
                                content=content,
                                metadata={
                                    "title": title,
                                    "section": " > ".join(str(item) for item in heading_path if str(item).strip()),
                                    "url": url,
                                    "type": page_type,
                                    "topic": topic,
                                    "date": str(payload.get("updated_date") or payload.get("publication_date") or "").strip(),
                                },
                            )
                        )
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("Unable to read local chunk file %s (%s)", self._chunks_path, exc)
                self._last_error = str(exc)

        if self._legacy_json_path is not None and self._legacy_json_path.exists():
            try:
                payload = json.loads(self._legacy_json_path.read_text(encoding="utf-8", errors="replace"))
                if isinstance(payload, dict):
                    for key, value in payload.items():
                        flattened = "\n".join(self._flatten_json(value, key_path=(str(key),))).strip()
                        if not flattened:
                            continue
                        section = str(key).replace("_", " ").strip().title()
                        chunks.append(
                            self._chunk_payload(
                                source=self._relative_source(self._legacy_json_path),
                                content=flattened,
                                metadata={"title": section, "section": section, "type": "legacy_json"},
                            )
                        )
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("Unable to read legacy JSON knowledge file %s (%s)", self._legacy_json_path, exc)
                self._last_error = str(exc)

        self._local_chunks_cache = list(chunks)
        self._local_alias_map = {key: set(value) for key, value in alias_map.items()}
        return chunks, alias_map

    def _expand_query_tokens(self, query: str, alias_map: dict[str, set[str]]) -> tuple[set[str], set[str]]:
        lowered_query = query.lower()
        query_tokens = self._normalize_tokens(query)
        alias_tokens: set[str] = set()
        for canonical, aliases in alias_map.items():
            group = {canonical, *{alias.lower() for alias in aliases}}
            if any(alias and alias in lowered_query for alias in group):
                for alias in aliases:
                    alias_tokens.update(self._normalize_tokens(alias))
                alias_tokens.update(self._normalize_tokens(canonical))
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

    def _query_prefers_history(self, query: str) -> bool:
        lowered = query.lower()
        return any(marker in lowered for marker in ("formerly", "called before", "old name", "previous", "history"))

    def _query_prefers_programs(self, query: str) -> bool:
        lowered = query.lower()
        return any(marker in lowered for marker in ("course", "courses", "program", "programs", "offered", "available"))

    def _query_prefers_leadership(self, query: str) -> bool:
        lowered = query.lower()
        return any(marker in lowered for marker in ("president", "dean", "director", "registrar"))

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
        metadata = chunk.get("metadata") or {}
        title = str(metadata.get("title") or "").lower()
        section = str(metadata.get("section") or "").lower()
        body = str(chunk.get("content") or "").lower()

        if alias_tokens:
            score += (len(alias_tokens & token_set) / max(1, len(alias_tokens))) * 4.0
        if query.lower().strip() and query.lower().strip() in body:
            score += 4.5
        for phrase in query_phrases:
            if phrase in body or phrase in title or phrase in section:
                score += 2.0 if len(phrase.split()) == 2 else 3.5
        if self._query_prefers_history(query):
            if any(marker in body for marker in ("formerly", "old name", "previous", "renamed", "sdssu", "sspsc", "sspc", "besc")):
                score += 4.0
        if self._query_prefers_programs(query):
            if any(marker in body for marker in ("bachelor of", "master of", "doctor of", "program", "course")):
                score += 4.0
            if "program" in section or "program" in title:
                score += 2.0
        if self._query_prefers_leadership(query):
            if any(marker in body for marker in ("president", "dean", "director", "registrar")):
                score += 4.0
        return score

    def _search_local_chunks(self, query: str) -> list[dict[str, Any]]:
        chunks, alias_map = self._load_local_legacy_chunks()
        if not chunks:
            self._last_retrieval_summary = "local:no_chunks"
            return []

        query_tokens, alias_tokens = self._expand_query_tokens(query, alias_map)
        query_phrases = self._query_phrases(query)
        ranked: list[dict[str, Any]] = []
        for chunk in chunks:
            score = self._score_chunk(
                chunk,
                query=query,
                query_tokens=query_tokens,
                query_phrases=query_phrases,
                alias_tokens=alias_tokens,
            )
            if score <= 0:
                continue
            ranked.append({**chunk, "_retrieval_score": round(score, 4)})
        ranked.sort(key=lambda item: float(item.get("_retrieval_score", 0.0)), reverse=True)
        self._last_retrieval_summary = "local:ranked" if ranked else "local:no_match"
        return ranked[:6]

    def _search_supabase_chunks(self, query: str) -> list[dict[str, Any]]:
        if not self._uses_supabase() or self._supabase_client is None:
            return []
        rows = self._supabase_client.search_chunks(query, limit=6)
        self._last_retrieval_summary = "supabase:ranked" if rows else "supabase:no_match"
        return rows

    def _select_relevant_chunks(self, query: str | None) -> list[dict[str, Any]]:
        query_text = (query or "").strip()
        if not query_text:
            return []
        if self._uses_supabase():
            return self._search_supabase_chunks(query_text)
        return self._search_local_chunks(query_text)

    def _format_chunk(self, chunk: dict[str, Any], *, max_chars: int) -> str:
        metadata = chunk.get("metadata") or {}
        parts = [f"Source: {chunk.get('source') or 'Unknown'}"]
        title = str(metadata.get("title") or "").strip()
        if title:
            parts.append(f"Title: {title}")
        section = str(metadata.get("section") or "").strip()
        if section:
            parts.append(f"Section: {section}")
        chunk_type = str(metadata.get("type") or "").strip()
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

    def _format_selected_chunks(self, selected: list[dict[str, Any]]) -> str:
        if not selected:
            return ""
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

    def _build_prompt(self, retrieved_context: str) -> str:
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
            "- You may still handle greetings, brief clarifications, and natural follow-up conversation tied to your NEMSU help role.\n"
            "- Allowed topics include procedures, admissions, enrollment, offices, contacts, schedules, campuses, facilities, services, directory information, programs, university history, leadership, historical names, aliases, and related institutional information.\n"
            "- Do not answer academic tutoring requests such as solving problems, explaining lessons, doing homework, writing essays, generating code for assignments, or teaching subject matter.\n"
            "- If the user asks for something clearly outside NEMSU scope, respond politely and redirect them to NEMSU-related help.\n\n"
            "Source priority:\n"
            "- Use the retrieved knowledge context below first.\n"
            "- Treat the retrieved context as authoritative before any model background knowledge.\n"
            "- If the answer is not stated in the retrieved context, say clearly that it is not available in the current knowledge base.\n"
            "- Do not hallucinate missing details.\n\n"
            "RETRIEVED KNOWLEDGE CONTEXT:\n"
            f"{retrieved_context}\n"
        )

    def preview_retrieval(
        self,
        query: str | None,
        conversation_history: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        del conversation_history
        with self._lock:
            chunks = self._select_relevant_chunks(query)
            return {
                "strategy": "supabase" if self._uses_supabase() else ("local" if chunks else "none"),
                "chunks": chunks,
                "context": self._format_selected_chunks(chunks),
                "max_score": max((float(chunk.get("_retrieval_score", 0.0)) for chunk in chunks), default=0.0),
            }

    def get_system_prompt(self) -> str:
        with self._lock:
            self._cached_prompt = self._cached_prompt or self._fallback_prompt()
            return self._cached_prompt

    def get_system_prompt_for_query(
        self,
        query: str | None,
        conversation_history: list[dict[str, str]] | None = None,
    ) -> str:
        del conversation_history
        with self._lock:
            chunks = self._select_relevant_chunks(query)
            return self._build_prompt(self._format_selected_chunks(chunks))

    def health(self) -> dict[str, str | bool | None | int]:
        chunk_count = 0
        detail: str | None = self._last_error or None
        if self._uses_supabase() and self._supabase_client is not None:
            status = self._supabase_client.health()
            chunk_count = int(status.get("chunk_count", 0) or 0)
            detail = str(status.get("detail") or detail or "") or None
            available = bool(status.get("available"))
            source_path = str(status.get("source_path") or "supabase://kb_chunks")
        else:
            local_chunks, _ = self._load_local_legacy_chunks()
            chunk_count = len(local_chunks)
            available = bool(local_chunks) or bool(self._markdown_path and self._markdown_path.exists())
            source_path = str(self._chunks_path or self._markdown_path or "legacy://kb_unconfigured")
        return {
            "available": available,
            "source_path": source_path,
            "detail": detail,
            "chunk_count": chunk_count,
        }
