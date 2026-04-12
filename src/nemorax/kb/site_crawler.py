from __future__ import annotations

import asyncio
from collections import deque
from pathlib import Path
from urllib import robotparser
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from .models import CrawlConfig, CrawlRecord
from .utils import append_jsonl, canonicalize_host, ensure_dir, is_probably_html, normalize_url, stable_id, utc_now_iso, write_json


class SiteCrawler:
    def __init__(self, config: CrawlConfig) -> None:
        self.config = config
        self.output_dir = Path(config.output_directory)
        self.log_dir = Path(config.log_directory)
        self.raw_html_dir = self.output_dir / "raw" / "html"
        self.manifest_path = self.output_dir / "raw" / "crawl_manifest.jsonl"
        self.skipped_path = self.log_dir / "crawl_skipped.jsonl"
        self.errors_path = self.log_dir / "crawl_errors.jsonl"
        ensure_dir(self.raw_html_dir)
        ensure_dir(self.log_dir)
        self.robots: dict[str, robotparser.RobotFileParser] = {}
        self.last_request: dict[str, float] = {}
        self.seen: set[str] = set()

    def _allowed(self, url: str) -> tuple[bool, str | None]:
        parsed = urlparse(url)
        host = canonicalize_host(parsed.netloc)
        if parsed.scheme not in {"http", "https"}:
            return False, "unsupported_scheme"
        if host in {canonicalize_host(item) for item in self.config.blocked_domains}:
            return False, "blocked_domain"
        if any(__import__("re").search(pattern, url, __import__("re").IGNORECASE) for pattern in self.config.exclude_patterns):
            return False, "exclude_pattern"
        if self.config.same_domain_only and host not in {canonicalize_host(item) for item in self.config.allowed_domains}:
            return False, "outside_primary_domain"
        if self.config.include_patterns and host in {canonicalize_host(item) for item in self.config.allowed_domains}:
            if not any(__import__("re").search(pattern, url, __import__("re").IGNORECASE) for pattern in self.config.include_patterns):
                return False, "not_in_include_scope"
        return True, None

    def _robots_allowed(self, url: str) -> bool:
        if not self.config.respect_robots_txt:
            return True
        parsed = urlparse(url)
        host = canonicalize_host(parsed.netloc)
        if host not in self.robots:
            parser = robotparser.RobotFileParser()
            parser.set_url(f"{parsed.scheme}://{host}/robots.txt")
            try:
                parser.read()
            except Exception:
                return True
            self.robots[host] = parser
        return self.robots[host].can_fetch(self.config.user_agent, url)

    async def _delay(self, host: str) -> None:
        now = asyncio.get_running_loop().time()
        last = self.last_request.get(host)
        if last is not None:
            remaining = self.config.crawl_delay_seconds - (now - last)
            if remaining > 0:
                await asyncio.sleep(remaining)
        self.last_request[host] = asyncio.get_running_loop().time()

    @staticmethod
    def _extract_links(html: str, base_url: str) -> tuple[str | None, str | None, list[str]]:
        soup = BeautifulSoup(html, "lxml")
        title = soup.title.get_text(" ", strip=True) if soup.title else None
        canonical = None
        tag = soup.find("link", rel=lambda value: value and "canonical" in value.lower())
        if tag and tag.get("href"):
            canonical = normalize_url(tag["href"], base_url=base_url)
        links = []
        for anchor in soup.find_all("a", href=True):
            href = anchor.get("href", "").strip()
            if href:
                links.append(normalize_url(href, base_url=base_url))
        return title, canonical, links

    async def crawl(self, resume: bool = True) -> dict[str, int]:
        if resume and self.manifest_path.exists():
            for line in self.manifest_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    self.seen.add(CrawlRecord.model_validate_json(line).normalized_url)
        queue: deque[tuple[str, int, str | None]] = deque([(str(self.config.start_url), 0, None)])
        discovered: set[str] = {normalize_url(str(self.config.start_url))}
        crawled = 0
        async with httpx.AsyncClient(headers={"User-Agent": self.config.user_agent}) as client:
            while queue and crawled < self.config.max_pages:
                url, depth, parent = queue.popleft()
                normalized = normalize_url(url)
                if normalized in self.seen:
                    continue
                self.seen.add(normalized)
                allowed, reason = self._allowed(normalized)
                if not allowed or not self._robots_allowed(normalized):
                    append_jsonl(self.skipped_path, {"url": url, "normalized_url": normalized, "parent_url": parent, "depth": depth, "reason": reason or "robots_txt", "skipped_at": utc_now_iso()})
                    continue
                try:
                    await self._delay(canonicalize_host(urlparse(normalized).netloc))
                    response = await client.get(normalized, follow_redirects=True, timeout=self.config.request_timeout_seconds)
                except Exception as exc:
                    append_jsonl(self.errors_path, {"url": normalized, "error": repr(exc), "timestamp": utc_now_iso()})
                    continue
                final_url = normalize_url(str(response.url))
                content_type = response.headers.get("content-type") or ""
                title = canonical = None
                links: list[str] = []
                html_path = None
                if is_probably_html(content_type, final_url) and response.status_code < 400:
                    html_path = str((self.raw_html_dir / f"{stable_id('crawl', final_url)}.html").resolve())
                    Path(html_path).write_text(response.text, encoding="utf-8")
                    title, canonical, links = self._extract_links(response.text, final_url)
                    crawled += 1
                record = CrawlRecord(
                    page_id=stable_id("page", canonical or final_url),
                    url=url,
                    normalized_url=normalized,
                    final_url=final_url,
                    canonical_url=canonical,
                    parent_url=parent,
                    depth=depth,
                    status_code=response.status_code,
                    content_type=content_type,
                    title=title,
                    html_path=html_path,
                    discovered_links=links,
                    skipped_reason=None if response.status_code < 400 else f"http_{response.status_code}",
                    crawl_timestamp=utc_now_iso(),
                )
                append_jsonl(self.manifest_path, record.model_dump(mode="json"))
                if depth >= self.config.max_depth:
                    continue
                for link in links:
                    if link in discovered or any(link.lower().endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".csv")):
                        discovered.add(link)
                        continue
                    discovered.add(link)
                    queue.append((link, depth + 1, final_url))
        summary = {"total_urls_discovered": len(discovered), "total_pages_crawled": crawled}
        write_json(self.output_dir / "raw" / "crawl_summary.json", summary)
        return summary
