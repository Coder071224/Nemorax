from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import dateparser

from .models import CrawlConfig

DOCUMENT_EXTENSIONS = {
    ".pdf",
    ".doc",
    ".docx",
    ".ppt",
    ".pptx",
    ".xls",
    ".xlsx",
    ".csv",
    ".txt",
    ".rtf",
}
TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "utm_campaign",
    "utm_content",
    "utm_medium",
    "utm_source",
    "utm_term",
}
STOPWORDS = {
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
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "to",
    "with",
    "this",
    "these",
    "those",
    "your",
    "you",
    "our",
    "their",
}


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def stable_hash(*parts: str, length: int = 16) -> str:
    digest = hashlib.sha256("||".join(parts).encode("utf-8")).hexdigest()
    return digest[:length]


def stable_id(prefix: str, *parts: str) -> str:
    return f"{prefix}_{stable_hash(*parts)}"


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def clean_text_block(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = text.replace("\u200b", "")
    return normalize_whitespace(text)


def normalize_text_for_match(text: str) -> str:
    lowered = clean_text_block(text).lower()
    lowered = re.sub(r"[^\w\s]+", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def ensure_directory(path: str | Path) -> Path:
    directory = Path(path)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def ensure_dir(path: str | Path) -> Path:
    return ensure_directory(path)


def save_text(path: str | Path, text: str) -> None:
    file_path = Path(path)
    ensure_directory(file_path.parent)
    file_path.write_text(text, encoding="utf-8")


def load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def dump_json(path: str | Path, payload: Any) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_json(path: str | Path, payload: Any) -> None:
    dump_json(path, payload)


def iter_jsonl(path: str | Path) -> Iterable[dict[str, Any]]:
    target = Path(path)
    if not target.exists():
        return []
    with target.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield json.loads(line)


def write_jsonl(path: str | Path, rows: Iterable[dict[str, Any]]) -> None:
    target = Path(path)
    ensure_directory(target.parent)
    with target.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def append_jsonl(path: str | Path, row: dict[str, Any]) -> None:
    target = Path(path)
    ensure_directory(target.parent)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def normalize_url(url: str, *, base_url: str | None = None, preserve_query: bool = False) -> str:
    resolved = urljoin(base_url or "", url.strip())
    parsed = urlparse(resolved)
    scheme = parsed.scheme.lower() or "https"
    netloc = parsed.netloc.lower()
    if netloc == "nemsu.edu.ph":
        netloc = "www.nemsu.edu.ph"
    path = parsed.path or "/"
    if path != "/" and not re.search(r"/[^/]+\.[a-z0-9]{1,6}$", path, re.I):
        path = path.rstrip("/")
        if not path:
            path = "/"
    query_pairs = []
    if preserve_query:
        query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
    else:
        for key, value in parse_qsl(parsed.query, keep_blank_values=True):
            lower_key = key.lower()
            if lower_key in TRACKING_QUERY_KEYS or lower_key.startswith("utm_"):
                continue
            if lower_key in {"sort", "share"}:
                continue
            query_pairs.append((key, value))
    query = urlencode(query_pairs, doseq=True)
    return urlunparse((scheme, netloc, path, "", query, ""))


def canonicalize_host(host: str) -> str:
    lowered = host.lower()
    if lowered == "nemsu.edu.ph":
        return "www.nemsu.edu.ph"
    return lowered


def is_same_domain(url: str, allowed_domains: Iterable[str]) -> bool:
    hostname = urlparse(url).hostname or ""
    return hostname in set(allowed_domains)


def looks_like_document_url(url: str) -> bool:
    parsed = urlparse(url)
    lower = parsed.path.lower()
    if any(lower.endswith(ext) for ext in DOCUMENT_EXTENSIONS):
        return True
    return any(domain in parsed.netloc.lower() for domain in ("drive.google.com", "docs.google.com", "app.box.com"))


def should_exclude_url(url: str, config: CrawlConfig) -> str | None:
    for pattern in config.exclude_patterns:
        if re.match(pattern, url, re.I):
            return f"matched exclude pattern: {pattern}"
    return None


def is_in_scope(url: str, config: CrawlConfig) -> bool:
    if config.same_domain_only and not is_same_domain(url, config.allowed_domains):
        return False
    if config.include_patterns and not any(re.match(pattern, url, re.I) for pattern in config.include_patterns):
        return False
    return should_exclude_url(url, config) is None


def should_visit_url(url: str, config: CrawlConfig, same_domain_only: bool = True) -> tuple[bool, str | None]:
    normalized = normalize_url(url)
    if same_domain_only and not is_same_domain(normalized, config.allowed_domains):
        return False, "outside_primary_domain"
    excluded = should_exclude_url(normalized, config)
    return excluded is None, excluded


def parse_date(value: str | None) -> str | None:
    if not value:
        return None
    dt = dateparser.parse(
        value,
        settings={
            "RETURN_AS_TIMEZONE_AWARE": True,
            "TIMEZONE": "UTC",
            "TO_TIMEZONE": "UTC",
        },
    )
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.isoformat()


def recency_days(iso_value: str | None) -> int | None:
    if not iso_value:
        return None
    try:
        parsed = datetime.fromisoformat(iso_value)
    except ValueError:
        return None
    return max(0, (datetime.now(UTC) - parsed.astimezone(UTC)).days)


def extract_years(text: str) -> list[int]:
    return sorted({int(match) for match in re.findall(r"\b(19\d{2}|20\d{2})\b", text or "")})


def detect_language(text: str, html_lang: str | None = None) -> str:
    if html_lang:
        return html_lang.split("-")[0].lower()
    lowered = normalize_text_for_match(text)
    if not lowered:
        return "unknown"
    english_hits = sum(1 for word in lowered.split() if word in STOPWORDS)
    if english_hits >= 3:
        return "en"
    return "unknown"


def sha256_text(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def approx_token_count(text: str) -> int:
    words = len((text or "").split())
    return int(words * 1.3)


def summarize_text(text: str, *, max_words: int = 40, max_sentences: int | None = None) -> str:
    words = (text or "").split()
    if max_sentences is not None:
        sentences = re.split(r"(?<=[.!?])\s+", clean_text_block(text))
        selected = " ".join(sentence for sentence in sentences[:max_sentences] if sentence)
        words = selected.split()
    if len(words) <= max_words:
        return " ".join(words)
    return " ".join(words[:max_words]).rstrip(",;:") + "..."


def top_keywords(text: str, limit: int = 10) -> list[str]:
    tokens = [token for token in normalize_text_for_match(text).split() if len(token) > 2 and token not in STOPWORDS]
    counts = Counter(tokens)
    return [token for token, _ in counts.most_common(limit)]


def split_words(text: str, max_words: int, overlap_words: int) -> list[str]:
    words = text.split()
    if len(words) <= max_words:
        return [text]
    segments: list[str] = []
    start = 0
    while start < len(words):
        end = min(len(words), start + max_words)
        segments.append(" ".join(words[start:end]))
        if end >= len(words):
            break
        start = max(0, end - overlap_words)
    return segments
