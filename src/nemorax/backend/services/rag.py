"""Semantic RAG module for Nemis using local ChromaDB retrieval."""

from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any

from nemorax.backend.core.logging import get_logger


logger = get_logger("nemorax.rag")

_MODULE_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _MODULE_DIR.parents[3]
_CHROMA_PATH = Path(
    os.getenv("NEMORAX_CHROMA_PATH", "").strip()
    or (
        str((Path(tempfile.gettempdir()) / "nemorax_chroma").resolve())
        if os.getenv("RENDER") or os.getenv("RENDER_SERVICE_ID")
        else str((_PROJECT_ROOT / ".chroma_db").resolve())
    )
)
_STATE_PATH = _CHROMA_PATH / "index_state.json"
_KB_DIRS = (_PROJECT_ROOT / "kb", _PROJECT_ROOT / "data")
_COLLECTION_NAME = "nemsu_kb"
_EMBED_MODEL = "all-MiniLM-L6-v2"
_CHUNK_CHARS = 1200
_OVERLAP_CHARS = 150
_TOP_K = 6
_MAX_CONTEXT_CHARS = 3000
_SUPPORTED_EXTENSIONS = {".txt", ".md", ".json", ".csv", ".jsonl"}
_SKIP_DIR_NAMES = {
    ".venv",
    "venv",
    "__pycache__",
    ".git",
    ".chroma_db",
    "node_modules",
    "dist",
    "build",
    "site-packages",
    "HISTORY",
    "USERS",
    "FEEDBACK",
    "raw",
}
_SKIP_FILE_NAMES = {
    "embeddings_ready.json",
    "qa_eval.json",
    "validation_summary.json",
    "crawl_manifest.jsonl",
    "documents_manifest.jsonl",
    "taxonomy.json",
    "entities.json",
    "relationships.json",
}
_MAX_FILE_SIZE_BYTES = 5_000_000
_ABBREVIATIONS = {
    "cite": "College of Information Technology Education",
    "cbm": "College of Business and Management",
    "cas": "College of Arts and Sciences",
    "coed": "College of Education",
    "coe": "College of Engineering",
    "cag": "College of Agriculture",
    "cthm": "College of Tourism and Hospitality Management",
    "cjc": "College of Justice and Criminology",
    "con": "College of Nursing",
    "cp": "College of Pharmacy",
    "nemsu": "Northeastern Mindanao State University",
    "besc": "Bukidnon External Studies Center",
    "sspc": "Surigao del Sur Polytechnic College",
    "sspsc": "Surigao del Sur Polytechnic State College",
    "sdssu": "Surigao del Sur State University",
    "bislig": "NEMSU Bislig Campus",
    "cantilan": "NEMSU Cantilan Campus",
    "lianga": "NEMSU Lianga Campus",
    "marihatag": "NEMSU Marihatag Campus",
    "tagbina": "NEMSU Tagbina Campus",
    "barobo": "NEMSU Barobo Campus",
    "lanuza": "NEMSU Lanuza Campus",
}

_model: Any = None
_client: Any = None
_collection: Any = None
_last_error = ""
_rag_disabled = False

IS_ANDROID = hasattr(sys, "getandroidapilevel")


def _disable_semantic_rag(reason: str, *, exc: Exception | None = None) -> None:
    global _rag_disabled, _last_error, _client, _collection
    _rag_disabled = True
    _last_error = reason
    _client = None
    _collection = None
    if exc is None:
        logger.warning("[RAG] Semantic retrieval disabled: %s", reason)
    else:
        logger.error("[RAG] Semantic retrieval disabled: %s", reason, exc_info=exc)


def _normalize(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text or "")
    cleaned = re.sub(r"[^\x00-\x7F]+", " ", cleaned)
    return cleaned.strip()


def _tokenize(text: str) -> set[str]:
    return {token for token in re.findall(r"\w+", (text or "").lower()) if len(token) >= 2}


def _expand(text: str) -> str:
    tokens = re.findall(r"\w+", (text or "").lower())
    return " ".join(_ABBREVIATIONS.get(token, token) for token in tokens)


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _read_state() -> dict[str, Any]:
    if not _STATE_PATH.exists():
        return {}
    try:
        return json.loads(_STATE_PATH.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("[RAG] Failed to read index state: %s", exc)
        return {}


def _write_state(payload: dict[str, Any]) -> None:
    try:
        _ensure_parent(_STATE_PATH)
        _STATE_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError as exc:
        logger.warning("[RAG] Failed to write index state: %s", exc)


def _load_model() -> Any:
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        logger.info("[RAG] Loading embedding model: %s", _EMBED_MODEL)
        _model = SentenceTransformer(_EMBED_MODEL)
        logger.info("[RAG] Embedding model ready")
    return _model


def _load_collection(*, reset: bool = False) -> Any:
    global _client, _collection
    if _rag_disabled:
        raise RuntimeError(_last_error or "Semantic retrieval is disabled.")
    import chromadb

    _CHROMA_PATH.mkdir(parents=True, exist_ok=True)
    if _client is None:
        try:
            _client = chromadb.PersistentClient(path=str(_CHROMA_PATH))
        except Exception as exc:
            _disable_semantic_rag(f"ChromaDB initialization failed at {_CHROMA_PATH}", exc=exc)
            raise RuntimeError(_last_error) from exc
    if reset:
        try:
            _client.delete_collection(_COLLECTION_NAME)
        except Exception:
            logger.debug("[RAG] No existing collection to delete during reset.")
        _collection = None
    if _collection is None:
        _collection = _client.get_or_create_collection(
            name=_COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info("[RAG] ChromaDB ready — collection: %s | docs: %d", _COLLECTION_NAME, _collection.count())
    return _collection


def _flatten_json(value: Any, *, prefix: str = "") -> list[str]:
    lines: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            next_prefix = f"{prefix}{key}" if not prefix else f"{prefix} > {key}"
            lines.extend(_flatten_json(item, prefix=next_prefix))
        return lines
    if isinstance(value, list):
        for index, item in enumerate(value, start=1):
            next_prefix = f"{prefix} > item_{index}" if prefix else f"item_{index}"
            lines.extend(_flatten_json(item, prefix=next_prefix))
        return lines
    text = _normalize(str(value))
    if text:
        label = prefix or "value"
        lines.append(f"{label}: {text}")
    return lines


def _titleize(name: str) -> str:
    return name.replace("_", " ").strip().title()


def _extract_record_title(section: str, value: dict[str, Any], index: int) -> str:
    candidates = (
        value.get("question"),
        value.get("name"),
        value.get("designation"),
        value.get("title"),
        value.get("id"),
    )
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return f"{_titleize(section)} {index}"


def _build_structured_blocks(value: Any, *, section: str) -> list[tuple[str, str]]:
    if isinstance(value, list):
        blocks: list[tuple[str, str]] = []
        for index, item in enumerate(value, start=1):
            if isinstance(item, dict):
                block = "\n".join(_flatten_json(item, prefix=section)).strip()
                if block:
                    blocks.append((_extract_record_title(section, item, index), block))
            else:
                block = "\n".join(_flatten_json(item, prefix=section)).strip()
                if block:
                    blocks.append((f"{_titleize(section)} {index}", block))
        return blocks

    if isinstance(value, dict):
        blocks: list[tuple[str, str]] = []
        split_keys = {
            key
            for key, item in value.items()
            if isinstance(item, list) and item and all(isinstance(entry, dict) for entry in item)
        }
        if split_keys:
            summary_payload = {key: item for key, item in value.items() if key not in split_keys}
            summary_block = "\n".join(_flatten_json(summary_payload, prefix=section)).strip()
            if summary_block:
                blocks.append((_titleize(section), summary_block))
            for key in split_keys:
                blocks.extend(_build_structured_blocks(value[key], section=f"{section} > {key}"))
            return blocks

    block = "\n".join(_flatten_json(value, prefix=section)).strip()
    return [(_titleize(section), block)] if block else []


def _load_json_text(path: Path) -> list[tuple[str, str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except json.JSONDecodeError as exc:
        logger.warning("[RAG] Malformed JSON skipped: %s — %s", path.as_posix(), exc)
        return []
    except OSError as exc:
        logger.warning("[RAG] Cannot read JSON file: %s — %s", path.as_posix(), exc)
        return []

    if isinstance(payload, dict):
        blocks: list[tuple[str, str]] = []
        for key, item in payload.items():
            blocks.extend(_build_structured_blocks(item, section=str(key)))
        return blocks

    block = "\n".join(_flatten_json(payload)).strip()
    return [("json", block)] if block else []


def _load_jsonl_text(path: Path) -> list[tuple[str, str]]:
    blocks: list[tuple[str, str]] = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for index, line in enumerate(handle, start=1):
                raw = line.strip()
                if not raw:
                    continue
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError as exc:
                    logger.warning("[RAG] Malformed JSONL record skipped: %s:%d — %s", path.as_posix(), index, exc)
                    continue
                if isinstance(payload, dict):
                    content = _normalize(
                        str(payload.get("raw_text") or payload.get("normalized_text") or "")
                    )
                    if not content:
                        content = "\n".join(_flatten_json(payload)).strip()
                    title = str(payload.get("title") or payload.get("topic") or path.stem).strip() or path.stem
                    if content:
                        blocks.append((title, content))
                else:
                    content = _normalize(str(payload))
                    if content:
                        blocks.append((f"{path.stem}:{index}", content))
    except OSError as exc:
        logger.warning("[RAG] Cannot read JSONL file: %s — %s", path.as_posix(), exc)
        return []
    return blocks


def _load_csv_text(path: Path) -> list[tuple[str, str]]:
    rows: list[str] = []
    try:
        with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
            reader = csv.DictReader(handle)
            for index, row in enumerate(reader, start=1):
                values = [f"{key}: {value}" for key, value in row.items() if key and value]
                if values:
                    rows.append(f"row {index}: " + "; ".join(values))
    except OSError as exc:
        logger.warning("[RAG] Cannot read CSV file: %s — %s", path.as_posix(), exc)
        return []
    return [(path.stem, "\n".join(rows).strip())] if rows else []


def _load_text_file(path: Path) -> list[tuple[str, str]]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        logger.warning("[RAG] Cannot read text file: %s — %s", path.as_posix(), exc)
        return []
    cleaned = text.strip()
    return [(path.stem, cleaned)] if cleaned else []


def _load_file(path: Path) -> list[tuple[str, str]]:
    suffix = path.suffix.lower()
    if suffix == ".json":
        return _load_json_text(path)
    if suffix == ".jsonl":
        return _load_jsonl_text(path)
    if suffix == ".csv":
        return _load_csv_text(path)
    return _load_text_file(path)


def _should_skip(path: Path) -> bool:
    try:
        if any(part in _SKIP_DIR_NAMES for part in path.parts):
            return True
        if path.name in _SKIP_FILE_NAMES:
            return True
        if path.suffix.lower() not in _SUPPORTED_EXTENSIONS:
            return True
        if path.stat().st_size > _MAX_FILE_SIZE_BYTES:
            logger.debug("[RAG] Skipping large file: %s", path.as_posix())
            return True
    except OSError as exc:
        logger.warning("[RAG] Failed to inspect file %s — %s", path.as_posix(), exc)
        return True
    return False


def _iter_source_files() -> list[Path]:
    files: list[Path] = []
    for kb_dir in _KB_DIRS:
        if not kb_dir.exists():
            logger.warning("[RAG] Knowledge directory not found, skipping: %s", kb_dir.as_posix())
            continue
        logger.info("[RAG] Scanning: %s", kb_dir.as_posix())
        for path in sorted(kb_dir.rglob("*")):
            if not path.is_file() or _should_skip(path):
                continue
            files.append(path)
    return files


def _source_fingerprint(files: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in files:
        try:
            stat = path.stat()
        except OSError:
            continue
        digest.update(str(path.relative_to(_PROJECT_ROOT)).encode("utf-8", errors="ignore"))
        digest.update(str(stat.st_mtime_ns).encode("ascii"))
        digest.update(str(stat.st_size).encode("ascii"))
    return digest.hexdigest()


def _chunk(text: str, *, source: str, section: str) -> list[dict[str, Any]]:
    normalized = _normalize(text)
    if not normalized:
        return []
    chunks: list[dict[str, Any]] = []
    start = 0
    index = 0
    while start < len(normalized):
        end = start + _CHUNK_CHARS
        chunk_text = normalized[start:end].strip()
        if len(chunk_text) < 40:
            break
        chunk_id = hashlib.md5(f"{source}:{section}:{index}".encode("utf-8"), usedforsecurity=False).hexdigest()
        chunks.append(
            {
                "id": chunk_id,
                "text": chunk_text,
                "source": source,
                "section": section,
                "chunk_idx": index,
            }
        )
        start += _CHUNK_CHARS - _OVERLAP_CHARS
        index += 1
    return chunks


def build_index(force: bool = False) -> None:
    global _last_error
    if IS_ANDROID or _rag_disabled:
        logger.info("[RAG] Android environment detected. Skipping local vector index.")
        return

    files = _iter_source_files()
    if not files:
        _last_error = "No readable knowledge files found in kb/ or data/."
        logger.error("[RAG] %s", _last_error)
        return

    fingerprint = _source_fingerprint(files)
    state = _read_state()
    try:
        collection = _load_collection()
        try:
            current_count = collection.count()
        except Exception:
            collection = _load_collection(reset=True)
            current_count = collection.count()
    except ImportError as exc:
        _last_error = f"Missing dependency: {exc}"
        logger.error("[RAG] Missing dependency: %s — run: pip install chromadb sentence-transformers", exc)
        return
    except Exception as exc:
        _disable_semantic_rag(str(exc), exc=exc)
        return

    if not force and current_count > 0 and state.get("fingerprint") == fingerprint:
        logger.info("[RAG] Index already up to date (%d chunks).", current_count)
        return

    try:
        collection = _load_collection(reset=True)
        model = _load_model()
    except ImportError as exc:
        _last_error = f"Missing dependency: {exc}"
        logger.error("[RAG] Missing dependency: %s — run: pip install chromadb sentence-transformers", exc)
        return
    except Exception as exc:
        _disable_semantic_rag(str(exc), exc=exc)
        return

    all_chunks: list[dict[str, Any]] = []
    files_loaded = 0
    for path in files:
        loaded_blocks = _load_file(path)
        if not loaded_blocks:
            continue
        files_loaded += 1
        relative_source = path.relative_to(_PROJECT_ROOT).as_posix()
        for section, text in loaded_blocks:
            all_chunks.extend(_chunk(text, source=relative_source, section=section))

    if not all_chunks:
        _last_error = "No chunks were produced from the knowledge base."
        logger.error("[RAG] %s", _last_error)
        return

    logger.info(
        "[RAG] Indexing: %d files scanned | %d loaded | %d chunks",
        len(files),
        files_loaded,
        len(all_chunks),
    )

    batch_size = 64
    for start in range(0, len(all_chunks), batch_size):
        batch = all_chunks[start : start + batch_size]
        texts = [item["text"] for item in batch]
        ids = [item["id"] for item in batch]
        metadatas = [
            {
                "source": item["source"],
                "section": item["section"],
                "chunk_idx": item["chunk_idx"],
            }
            for item in batch
        ]
        embeddings = model.encode(texts, show_progress_bar=False).tolist()
        collection.upsert(ids=ids, embeddings=embeddings, documents=texts, metadatas=metadatas)

    _last_error = ""
    _write_state(
        {
            "fingerprint": fingerprint,
            "chunk_count": collection.count(),
            "files_scanned": len(files),
            "files_loaded": files_loaded,
        }
    )
    logger.info("[RAG] Index built successfully. Total chunks: %d", collection.count())


def retrieve(query: str, conversation_history: list[dict[str, str]] | None = None, top_k: int = _TOP_K) -> list[dict[str, Any]]:
    global _last_error
    if IS_ANDROID or _rag_disabled or not query or not query.strip():
        return []

    try:
        collection = _load_collection()
        if collection.count() == 0:
            logger.warning("[RAG] Index is empty. Attempting build before retrieval.")
            build_index()
            collection = _load_collection()
            if collection.count() == 0:
                return []
        model = _load_model()
    except ImportError as exc:
        _last_error = f"Missing dependency: {exc}"
        logger.error("[RAG] Missing dependency during retrieval: %s", exc)
        return []
    except Exception as exc:
        _disable_semantic_rag(str(exc), exc=exc)
        return []

    history_bits = [
        _normalize(str(item.get("content", "")))
        for item in (conversation_history or [])[-6:]
        if isinstance(item, dict) and str(item.get("content", "")).strip()
    ]
    expanded_query = _expand(query)
    lowered_query = _normalize(query.lower())
    if "president" in lowered_query:
        expanded_query += " who is the president of nemsu university president current president dr nemesio g loayon"
    if any(marker in lowered_query for marker in ("formerly", "called before", "old name", "previous", "used to")):
        expanded_query += " former names alias renamed surigao del sur state university sdssu surigao del sur polytechnic state college sspsc surigao del sur polytechnic college sspc bukidnon external studies center besc"
    if lowered_query.startswith("what is nemsu") or "what is nemsu" in lowered_query:
        expanded_query += " stands for north eastern mindanao state university official name"
    if "established" in lowered_query or "founded" in lowered_query:
        expanded_query += " history established founded 1982 1992 2021 republic act 11584"
    if any(token in lowered_query for token in ("year", "date", "when")) and any(
        token in " ".join(history_bits).lower() for token in ("formerly", "called before", "old name", "history", "renamed", "besc", "sdssu")
    ):
        expanded_query += " history timeline milestones former names dates 1982 1992 1998 2010 2021 republic act 11584"
    retrieval_query = expanded_query
    if history_bits:
        retrieval_query = f"{expanded_query} Conversation context: {' '.join(history_bits[-4:])}"

    logger.debug("[RAG] Query: %r | Expanded: %r", query, retrieval_query)

    try:
        embedding = model.encode([retrieval_query], show_progress_bar=False).tolist()[0]
        candidate_count = min(max(top_k * 8, 24), collection.count())
        results = collection.query(
            query_embeddings=[embedding],
            n_results=candidate_count,
            include=["documents", "metadatas", "distances"],
        )
    except Exception as exc:
        _disable_semantic_rag(str(exc), exc=exc)
        return []

    documents = results.get("documents") or [[]]
    metadatas = results.get("metadatas") or [[]]
    distances = results.get("distances") or [[]]
    matches: list[dict[str, Any]] = []
    history_context = " ".join(history_bits[-4:])
    query_tokens = _tokenize(f"{query} {history_context}".strip())
    normalized_query = lowered_query
    history_lower = history_context.lower()
    for document, metadata, distance in zip(documents[0], metadatas[0], distances[0]):
        if not document:
            continue
        semantic_score = round(1 - float(distance), 4)
        body = _normalize(document.lower())
        body_tokens = _tokenize(body)
        overlap_score = len(query_tokens & body_tokens) / max(1, len(query_tokens))
        rerank_score = semantic_score + overlap_score
        source = str((metadata or {}).get("source", "unknown"))
        section = str((metadata or {}).get("section", "")).lower()
        source_suffix = Path(source).suffix.lower()
        if source_suffix == ".json":
            rerank_score += 0.08
        if source_suffix == ".md":
            rerank_score -= 0.03
        if "president" in query_tokens and any(token in body for token in ("current president", "university president", "loayon")):
            rerank_score += 0.35
        if "president" in query_tokens and any(token in body for token in ("who is the president of nemsu", "current_president", "designation: university president", "question: who is the president of nemsu")):
            rerank_score += 0.45
        if any(marker in normalized_query for marker in ("formerly", "called before", "old name", "previous", "before")) and any(
            token in body for token in ("formerly", "renaming", "former", "surigao del sur state university", "bukidnon external studies center")
        ):
            rerank_score += 0.35
        if any(marker in normalized_query for marker in ("formerly", "called before", "old name", "previous", "before")) and any(
            token in body for token in ("formerly_known_as", "question: what is nemsu", "republic act 11584", "renamed sdssu to north eastern mindanao state university")
        ):
            rerank_score += 0.35
        if normalized_query.startswith("what is nemsu") and any(
            token in body for token in ("north eastern mindanao state university", "abbreviation", "institution > name")
        ):
            rerank_score += 0.3
        if "established" in query_tokens and any(token in body for token in ("1982", "1992", "established", "traces its roots")):
            rerank_score += 0.25
        if any(token in normalized_query for token in ("year", "date", "when")) and any(
            token in history_lower for token in ("formerly", "called before", "old name", "history", "renamed", "besc", "sdssu")
        ) and any(token in body for token in ("1982", "1992", "1998", "2010", "2021", "july 30, 2021", "history", "key_milestones")):
            rerank_score += 0.45
        if "dean" in query_tokens and any(token in body for token in ("question: who is the dean", "designation: dean", "dean is")):
            rerank_score += 0.25
        if any(token in query_tokens for token in ("bislig", "cbm", "cite")) and any(token in body for token in ("bislig campus", "college of business and management", "college of it education")):
            rerank_score += 0.18
        if section in {"history", "institution", "faq", "directory"}:
            rerank_score += 0.08
        match = {
            "text": document,
            "source": source,
            "section": (metadata or {}).get("section", ""),
            "score": round(rerank_score, 4),
        }
        matches.append(match)
        logger.debug("[RAG] Match: score=%.3f source=%s section=%s", rerank_score, match["source"], match["section"])

    matches.sort(key=lambda item: item["score"], reverse=True)
    matches = matches[:top_k]
    logger.info("[RAG] Retrieved %d chunks | top score: %.3f", len(matches), matches[0]["score"] if matches else 0.0)
    return matches


def format_context(chunks: list[dict[str, Any]]) -> str:
    if not chunks:
        return ""
    parts: list[str] = []
    for index, chunk in enumerate(chunks, start=1):
        header = f"[Source {index}: {chunk['source']}"
        section = str(chunk.get("section", "")).strip()
        if section:
            header += f" | section: {section}"
        header += f" | relevance: {chunk['score']:.2f}]"
        parts.append(f"{header}\n{chunk['text']}")
    context = "\n\n---\n\n".join(parts)
    if len(context) > _MAX_CONTEXT_CHARS:
        context = context[:_MAX_CONTEXT_CHARS].rstrip() + "\n\n[Context truncated]"
    return context


def health() -> dict[str, Any]:
    if _rag_disabled:
        return {
            "available": any(path.exists() for path in _KB_DIRS),
            "source_path": str(_CHROMA_PATH),
            "detail": _last_error or "Semantic retrieval is disabled.",
            "chunk_count": 0,
        }
    try:
        count = _load_collection().count()
    except ImportError as exc:
        return {
            "available": False,
            "source_path": str(_CHROMA_PATH),
            "detail": f"Missing dependency: {exc}",
        }
    except Exception as exc:
        return {
            "available": False,
            "source_path": str(_CHROMA_PATH),
            "detail": str(exc),
        }
    return {
        "available": bool(count) or any(path.exists() for path in _KB_DIRS),
        "source_path": str(_CHROMA_PATH),
        "detail": _last_error or None,
        "chunk_count": count,
    }
