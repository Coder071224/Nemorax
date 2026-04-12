from __future__ import annotations

import asyncio
import json
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from urllib import robotparser
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from .models import CrawlConfig, CrawlRecord
from .utils import append_jsonl, ensure_directory, is_in_scope, looks_like_document_url, normalize_url, should_exclude_url, stable_id, utc_now_iso


@dataclass(slots=True)
class CrawlTask:
    url: str
    depth: int
    parent_url: str | None = None


class SiteCrawler:
    def __init__(self, config: CrawlConfig, output_root: Path):
        self.config = config
        self.output_root = output_root
        self.raw_root = ensure_directory(output_root / "raw")
        self.html_root = ensure_directory(self.raw_root / "html")
        self.log_root = ensure_directory(Path(config.log_directory))
        self.manifest_path = self.raw_root / "crawl_manifest.jsonl"
        self.error_log_path = self.log_root / "crawl_errors.jsonl"
        self._visited: set[str] = set()
        self._robots = robotparser.RobotFileParser()
        self._last_request_by_domain: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def crawl(self, *, resume: bool = True) -> list[CrawlRecord]:
        if resume and self.manifest_path.exists():
            for row in self.manifest_path.read_text(encoding="utf-8").splitlines():
                if row.strip():
                    payload = json.loads(row)
                    self._visited.add(payload["normalized_url"])
        await self._load_robots()
        queue: deque[CrawlTask] = deque([CrawlTask(url=str(self.config.start_url), depth=0, parent_url=None)])
        records: list[CrawlRecord] = []
        async with httpx.AsyncClient(
            follow_redirects=True,
            headers={"User-Agent": self.config.user_agent},
            timeout=self.config.request_timeout_seconds,
        ) as client:
            while queue and len(records) < self.config.max_pages:
                task = queue.popleft()
                normalized = normalize_url(task.url, base_url=str(self.config.start_url))
                if normalized in self._visited:
                    continue
                self._visited.add(normalized)
                excluded_reason = should_exclude_url(normalized, self.config)
                if excluded_reason:
                    continue
                if not self._robots.can_fetch(self.config.user_agent, normalized):
                    continue
                record = await self._fetch(client, task, normalized)
                if record is None:
                    continue
                records.append(record)
                append_jsonl(self.manifest_path, record.model_dump(mode="json"))
                if task.depth >= self.config.max_depth:
                    continue
                for link in record.discovered_links:
                    normalized_link = normalize_url(link, base_url=record.final_url)
                    if looks_like_document_url(normalized_link):
                        continue
                    if normalized_link in self._visited:
                        continue
                    if not is_in_scope(normalized_link, self.config):
                        continue
                    queue.append(CrawlTask(url=normalized_link, depth=task.depth + 1, parent_url=record.final_url))
        return records

    async def _load_robots(self) -> None:
        robots_url = normalize_url("/robots.txt", base_url=str(self.config.start_url))
        async with httpx.AsyncClient(
            follow_redirects=True,
            headers={"User-Agent": self.config.user_agent},
            timeout=self.config.request_timeout_seconds,
        ) as client:
            response = await client.get(robots_url)
            self._robots.parse(response.text.splitlines())

    async def _fetch(self, client: httpx.AsyncClient, task: CrawlTask, normalized_url: str) -> CrawlRecord | None:
        domain = urlparse(normalized_url).netloc
        async with self._lock:
            last_request = self._last_request_by_domain.get(domain)
            now = asyncio.get_running_loop().time()
            if last_request is not None:
                elapsed = now - last_request
                if elapsed < self.config.crawl_delay_seconds:
                    await asyncio.sleep(self.config.crawl_delay_seconds - elapsed)
            self._last_request_by_domain[domain] = asyncio.get_running_loop().time()
        try:
            response = await client.get(normalized_url)
        except Exception as exc:
            append_jsonl(
                self.error_log_path,
                {
                    "url": normalized_url,
                    "parent_url": task.parent_url,
                    "error": repr(exc),
                    "crawl_timestamp": utc_now_iso(),
                },
            )
            return None
        content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
        if "text/html" not in content_type:
            return None
        html = response.text
        soup = BeautifulSoup(html, "lxml")
        title = soup.title.get_text(" ", strip=True) if soup.title else None
        final_url = normalize_url(str(response.url))
        page_id = stable_id("page", final_url)
        html_path = self.html_root / f"{page_id}.html"
        html_path.write_text(html, encoding="utf-8")
        links = []
        for tag in soup.find_all("a", href=True):
            href = tag["href"].strip()
            if href.startswith(("mailto:", "tel:", "javascript:")):
                continue
            links.append(normalize_url(href, base_url=final_url))
        canonical_tag = soup.find("link", rel=lambda value: value and "canonical" in value.lower())
        canonical_url = normalize_url(canonical_tag["href"], base_url=final_url) if canonical_tag and canonical_tag.get("href") else None
        return CrawlRecord(
            page_id=page_id,
            url=task.url,
            normalized_url=normalized_url,
            final_url=final_url,
            canonical_url=canonical_url,
            parent_url=task.parent_url,
            depth=task.depth,
            status_code=response.status_code,
            content_type=content_type,
            title=title,
            html_path=str(html_path),
            discovered_links=list(dict.fromkeys(links)),
            crawl_timestamp=utc_now_iso(),
        )
