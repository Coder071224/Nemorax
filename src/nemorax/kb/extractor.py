from __future__ import annotations

import copy
import re
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import trafilatura
from bs4 import BeautifulSoup, NavigableString, Tag

from .classification import classify_freshness, classify_page_type
from .models import CrawlRecord, HeadingRecord, PageRecord, SectionRecord
from .utils import clean_text_block, detect_language, normalize_url, parse_date, sha256_text, stable_id, summarize_text

NOISE_SELECTORS = [
    "script",
    "style",
    "noscript",
    "header",
    "footer",
    "nav",
    "form",
    ".navbar",
    ".footer",
    ".social",
    ".share",
    ".pagination",
    ".carousel",
    ".slick-slider",
    ".dropdown-menu",
    ".modal",
]
CONTENT_SELECTORS = [
    "main",
    "article",
    "[role='main']",
    ".page-content",
    ".entry-content",
    ".content",
    ".main-content",
    ".container",
]
DATE_PATTERNS = [
    re.compile(r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}\b"),
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
]


class PageExtractor:
    def extract(self, crawl_record: CrawlRecord) -> PageRecord | None:
        if not crawl_record.html_path:
            return None
        html = Path(crawl_record.html_path).read_text(encoding="utf-8", errors="ignore")
        soup = BeautifulSoup(html, "lxml")
        title = clean_text_block(soup.title.get_text(" ", strip=True) if soup.title else "") or crawl_record.title or crawl_record.normalized_url
        meta_description = self._meta_content(soup, "description")
        canonical_url = self._canonical_url(soup, crawl_record.final_url)
        breadcrumb = self._extract_breadcrumb(soup)
        content_root = self._select_content_root(soup)
        if content_root is None:
            return None
        root = copy.deepcopy(content_root)
        self._strip_noise(root)
        headings, sections, tables = self._extract_sections(root)
        trafilatura_text = trafilatura.extract(
            html,
            include_links=True,
            include_tables=True,
            include_formatting=False,
            favor_recall=True,
        ) or ""
        section_text = "\n\n".join(section.text for section in sections)
        cleaned_main_body_text = clean_text_block(section_text or trafilatura_text)
        if not cleaned_main_body_text:
            return None
        publication_date, updated_date = self._extract_dates(soup, cleaned_main_body_text)
        page_type = classify_page_type(canonical_url, title, cleaned_main_body_text)
        freshness = classify_freshness(page_type, canonical_url, cleaned_main_body_text)
        extraction_confidence = self._confidence_score(cleaned_main_body_text, headings, tables)
        return PageRecord(
            page_id=crawl_record.page_id,
            url=crawl_record.final_url,
            canonical_url=canonical_url,
            title=title,
            meta_description=meta_description,
            page_type=page_type,
            freshness=freshness,
            breadcrumb=breadcrumb,
            headings=headings,
            sections=sections,
            cleaned_main_body_text=cleaned_main_body_text,
            structured_tables=tables,
            publication_date=publication_date,
            updated_date=updated_date,
            detected_language=detect_language(cleaned_main_body_text, soup.html.get("lang") if soup.html else None),
            content_hash=sha256_text(cleaned_main_body_text),
            source_domain=urlparse(crawl_record.final_url).netloc,
            crawl_timestamp=crawl_record.crawl_timestamp,
            extraction_confidence=extraction_confidence,
            source_links=crawl_record.discovered_links,
            provenance={
                "crawl_url": crawl_record.url,
                "short_summary": summarize_text(cleaned_main_body_text),
            },
        )

    def _meta_content(self, soup: BeautifulSoup, name: str) -> str | None:
        for attrs in ({"name": name}, {"property": f"og:{name}"}):
            tag = soup.find("meta", attrs=attrs)
            if tag and tag.get("content"):
                return clean_text_block(tag["content"])
        return None

    def _canonical_url(self, soup: BeautifulSoup, fallback: str) -> str:
        link = soup.find("link", rel=lambda value: value and "canonical" in value.lower())
        href = link.get("href") if link else fallback
        return normalize_url(href, base_url=fallback)

    def _extract_breadcrumb(self, soup: BeautifulSoup) -> list[str]:
        text = soup.get_text(" ", strip=True)
        match = re.search(r"You are now at:\s*(.+?)\s*>>\s*(.+?)(?:\s{2,}|$)", text)
        if match:
            return [clean_text_block(match.group(1)), clean_text_block(match.group(2))]
        crumbs = []
        for selector in (".breadcrumb li", ".breadcrumbs li", ".breadcrumb a", ".breadcrumbs a"):
            for node in soup.select(selector):
                label = clean_text_block(node.get_text(" ", strip=True))
                if label:
                    crumbs.append(label)
        return list(dict.fromkeys(crumbs))

    def _select_content_root(self, soup: BeautifulSoup) -> Tag | None:
        candidates: list[tuple[int, Tag]] = []
        for selector in CONTENT_SELECTORS:
            for node in soup.select(selector):
                text = clean_text_block(node.get_text(" ", strip=True))
                if len(text) >= 120:
                    candidates.append((len(text), node))
        if candidates:
            candidates.sort(key=lambda item: item[0], reverse=True)
            return candidates[0][1]
        return soup.body

    def _strip_noise(self, root: Tag) -> None:
        for selector in NOISE_SELECTORS:
            for node in root.select(selector):
                node.decompose()

    def _extract_sections(self, root: Tag) -> tuple[list[HeadingRecord], list[SectionRecord], list[dict[str, Any]]]:
        headings: list[HeadingRecord] = []
        sections: list[SectionRecord] = []
        tables: list[dict[str, Any]] = []
        heading_path: list[str] = []
        buffer: list[str] = []
        current_level = 1

        def flush_section() -> None:
            nonlocal buffer
            text = clean_text_block("\n".join(buffer))
            if not text:
                buffer = []
                return
            section_id = stable_id("section", "|".join(heading_path) or "root", text[:120])
            sections.append(SectionRecord(heading_path=list(heading_path), text=text, section_id=section_id))
            buffer = []

        for node in root.descendants:
            if isinstance(node, NavigableString) or not isinstance(node, Tag):
                continue
            if node.name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
                flush_section()
                level = int(node.name[1])
                text = clean_text_block(node.get_text(" ", strip=True))
                if not text:
                    continue
                headings.append(HeadingRecord(level=level, text=text, anchor=node.get("id")))
                current_level = level
                heading_path = heading_path[: level - 1]
                heading_path.append(text)
                continue
            if node.name == "p":
                text = clean_text_block(node.get_text(" ", strip=True))
                if text:
                    buffer.append(text)
            elif node.name in {"ul", "ol"}:
                items = []
                for li in node.find_all("li", recursive=False):
                    item = clean_text_block(li.get_text(" ", strip=True))
                    if item:
                        items.append(f"- {item}")
                if items:
                    buffer.append("\n".join(items))
            elif node.name == "table":
                table_rows = []
                for row in node.find_all("tr"):
                    cells = [clean_text_block(cell.get_text(" ", strip=True)) for cell in row.find_all(["th", "td"])]
                    if any(cells):
                        table_rows.append(cells)
                if table_rows:
                    tables.append({"heading_path": list(heading_path), "rows": table_rows})
                    buffer.append(self._table_to_text(table_rows))
            elif node.name == "blockquote":
                text = clean_text_block(node.get_text(" ", strip=True))
                if text:
                    buffer.append(text)
        flush_section()
        if not headings:
            headings.append(HeadingRecord(level=current_level, text="Overview"))
        if not sections:
            full_text = clean_text_block(root.get_text("\n", strip=True))
            if full_text:
                sections.append(
                    SectionRecord(
                        heading_path=["Overview"],
                        text=full_text,
                        section_id=stable_id("section", "overview", full_text[:120]),
                    )
                )
        return headings, sections, tables

    def _table_to_text(self, rows: list[list[str]]) -> str:
        lines = []
        for row in rows:
            cleaned_row = [cell for cell in row if cell]
            if cleaned_row:
                lines.append(" | ".join(cleaned_row))
        return "\n".join(lines)

    def _extract_dates(self, soup: BeautifulSoup, text: str) -> tuple[str | None, str | None]:
        published = None
        updated = None
        for attrs in (
            {"property": "article:published_time"},
            {"name": "pubdate"},
            {"property": "og:updated_time"},
            {"property": "article:modified_time"},
        ):
            tag = soup.find("meta", attrs=attrs)
            if tag and tag.get("content"):
                key = next(iter(attrs.values()))
                if "published" in key or "pubdate" in key:
                    published = published or parse_date(tag["content"])
                else:
                    updated = updated or parse_date(tag["content"])
        if not published:
            time_tag = soup.find("time")
            if time_tag:
                published = parse_date(time_tag.get("datetime") or time_tag.get_text(" ", strip=True))
        if not published:
            for pattern in DATE_PATTERNS:
                match = pattern.search(text[:1200])
                if match:
                    published = parse_date(match.group(0))
                    if published:
                        break
        return published, updated

    def _confidence_score(self, text: str, headings: list[HeadingRecord], tables: list[dict[str, Any]]) -> float:
        score = 0.3
        if len(text) >= 300:
            score += 0.25
        if len(text) >= 1200:
            score += 0.15
        if headings:
            score += 0.15
        if tables:
            score += 0.05
        boilerplate_hits = Counter(
            token for token in ("Directory", "Online Services", "Toggle navigation") if token.lower() in text.lower()
        )
        if boilerplate_hits:
            score -= min(0.15, 0.05 * sum(boilerplate_hits.values()))
        return max(0.05, min(score, 0.99))
