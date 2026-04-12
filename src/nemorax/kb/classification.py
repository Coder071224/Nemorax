from __future__ import annotations

import re

from .utils import clean_text_block, extract_years


def classify_page_type(url: str, title: str, text: str) -> str:
    lowered_url = url.lower()
    lowered_title = (title or "").lower()
    lowered_text = (text or "").lower()
    if any(token in lowered_url for token in ("/aboutus", "/history")):
        return "about"
    if any(token in lowered_url for token in ("/administration", "/board-of-regents")):
        return "governance"
    if any(token in lowered_url for token in ("/academics/programs", "/prospectus")):
        return "program_catalog"
    if "/academics/" in lowered_url:
        return "academics"
    if any(token in lowered_url for token in ("/guidance", "/registrar", "/library", "/office")):
        return "office/service"
    if any(token in lowered_url for token in ("/admission", "/enrolment")):
        return "admissions"
    if re.search(r"/news(?:/|$)", lowered_url):
        return "news"
    if any(token in lowered_url for token in ("/announcements", "/announcement")):
        return "announcement"
    if any(token in lowered_url for token in ("/events", "/event")):
        return "event"
    if "/jobs" in lowered_url or "career" in lowered_title:
        return "jobs"
    if any(token in lowered_url for token in ("/procurement", "/bac", "/bids")):
        return "procurement"
    if any(token in lowered_url for token in ("/transparency", "/foi", "/citizens-charter", "/arta")):
        return "transparency"
    if any(token in lowered_url for token in ("/documents", "/manual", "/policy")):
        if "form" in lowered_title or "form" in lowered_text:
            return "forms"
        if "manual" in lowered_title or "policy" in lowered_title:
            return "policy/manual"
        return "external_document" if lowered_url.endswith(".pdf") else "policy/manual"
    if any(token in lowered_url for token in ("/facilities", "/campus", "#cantilan-campus", "#bislig-campus")):
        return "campus_info"
    if any(token in lowered_url for token in ("/gallery", "/media")):
        return "gallery/media"
    if "form" in lowered_title or "downloadable" in lowered_title:
        return "forms"
    if any(token in lowered_text for token in ("citizen’s charter", "citizen's charter", "freedom of information")):
        return "transparency"
    return "other"


def classify_freshness(page_type: str, url: str, text: str) -> str:
    if page_type in {"news", "announcement", "event", "jobs", "procurement"}:
        return "time-sensitive"
    lowered = clean_text_block(f"{url} {text}").lower()
    years = extract_years(lowered)
    if "history" in lowered or "formerly" in lowered or len(years) >= 4:
        return "archival/historical"
    return "evergreen"
