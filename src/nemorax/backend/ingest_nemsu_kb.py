"""Structured NEMSU knowledge-base ingestion into Supabase."""

from __future__ import annotations

import argparse
import io
import re
import time
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib import robotparser
from urllib.parse import urlparse

import httpx
import trafilatura
from bs4 import BeautifulSoup
from pypdf import PdfReader

from nemorax.backend.core.logging import get_logger
from nemorax.backend.core.settings import settings
from nemorax.backend.core.errors import PersistenceError
from nemorax.backend.repositories.supabase_client import SupabasePersistenceClient
from nemorax.kb.utils import (
    approx_token_count,
    clean_text_block,
    normalize_text_for_match,
    normalize_url,
    parse_date,
    sha256_text,
    stable_id,
    summarize_text,
)


logger = get_logger("nemorax.structured_kb_ingest")

_BATCH_SIZE = 100
_HTTP_HEADERS = {"User-Agent": "NEMSU-KB-Bot/2.0 (knowledge-base ingestion)"}
_FB_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; NEMSU-KB-Bot/2.0)"}
_BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
_NEMSU_DOMAINS = {"www.nemsu.edu.ph", "nemsu.edu.ph"}
_DOCUMENT_DOMAINS = {"app.box.com", "docs.google.com", "drive.google.com"}
_SKIP_URL_RE = re.compile(
    r"(login|signin|wp-admin|wp-login|/feed|/tag/|/archive|replytocom=|mailto:|javascript:|/page/\d+/?$)",
    re.I,
)
_PROGRAM_RE = re.compile(r"\b(Bachelor|Master|Doctor|Juris Doctor|Diploma|BS|BA|MS|MA|PhD|EdD)\b", re.I)
_PHONE_RE = re.compile(r"(\(?\d{2,4}\)?[\s-]*\d{3}[\s-]*\d{3,4})")
_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)


@dataclass(frozen=True, slots=True)
class SourceSeed:
    url: str
    source_type: str
    source_name: str
    trust_tier: int
    category: str
    crawl: bool = True


@dataclass(slots=True)
class FetchedDocument:
    canonical_url: str
    source_id: str
    source_type: str
    source_name: str
    trust_tier: int
    category: str
    title: str
    document_type: str
    campus: str | None
    office: str | None
    published_at: str | None
    raw_text: str
    cleaned_text: str
    html: str | None
    metadata: dict[str, Any]


OFFICIAL_SITE_SEEDS: tuple[SourceSeed, ...] = (
    SourceSeed("https://www.nemsu.edu.ph/", "official_site", "NEMSU Official Website", 1, "institution"),
    SourceSeed("https://www.nemsu.edu.ph/aboutus", "official_site", "NEMSU About Us", 1, "institution"),
    SourceSeed("https://nemsu.edu.ph/directory", "official_site", "NEMSU Directory", 1, "directory"),
    SourceSeed("https://www.nemsu.edu.ph/administration", "official_site", "NEMSU Administration", 1, "administration"),
    SourceSeed("https://www.nemsu.edu.ph/academics/programs", "official_site", "NEMSU Programs", 1, "academics"),
    SourceSeed("https://www.nemsu.edu.ph/academics/guidance", "official_site", "NEMSU Guidance", 1, "student_services"),
    SourceSeed("https://www.nemsu.edu.ph/academics/registrar", "official_site", "NEMSU Registrar", 1, "student_services"),
    SourceSeed("https://www.nemsu.edu.ph/academics/library", "official_site", "NEMSU Library", 1, "student_services"),
    SourceSeed("https://www.nemsu.edu.ph/academics/enrolment", "official_site", "NEMSU Enrolment", 1, "student_services"),
    SourceSeed("https://www.nemsu.edu.ph/students/admission", "official_site", "NEMSU Admission", 1, "admissions"),
    SourceSeed("https://www.nemsu.edu.ph/news", "official_site", "NEMSU News", 1, "news"),
    SourceSeed("https://www.nemsu.edu.ph/announcements", "official_site", "NEMSU Announcements", 1, "announcements"),
    SourceSeed("https://www.nemsu.edu.ph/events", "official_site", "NEMSU Events", 1, "events"),
    SourceSeed("https://www.nemsu.edu.ph/bac-matters", "official_site", "NEMSU BAC Matters", 1, "procurement"),
    SourceSeed("https://www.nemsu.edu.ph/jobs", "official_site", "NEMSU Jobs", 1, "jobs"),
    SourceSeed("https://www.nemsu.edu.ph/citizens-charter", "official_site", "NEMSU Citizen's Charter", 1, "governance"),
    SourceSeed("https://www.nemsu.edu.ph/transparency-seal", "official_site", "NEMSU Transparency Seal", 1, "governance"),
    SourceSeed("https://www.nemsu.edu.ph/facilities", "official_site", "NEMSU Facilities", 1, "facilities"),
    SourceSeed("https://www.nemsu.edu.ph/calendar", "official_site", "NEMSU Calendar", 1, "calendar"),
    SourceSeed("https://www.nemsu.edu.ph/documents", "official_site", "NEMSU Documents", 1, "documents"),
    SourceSeed("https://www.nemsu.edu.ph/downloadables", "official_site", "NEMSU Downloadables", 1, "downloadables"),
    SourceSeed("https://www.nemsu.edu.ph/president-corner", "official_site", "NEMSU President Corner", 1, "administration"),
    SourceSeed("https://www.nemsu.edu.ph/academics/colleges/college-of-business-and-management", "official_site", "NEMSU CBM", 1, "academics"),
    SourceSeed("https://www.nemsu.edu.ph/academics/colleges/college-of-engineering-and-technology", "official_site", "NEMSU COET", 1, "academics"),
    SourceSeed("https://www.nemsu.edu.ph/academics/colleges/college-of-information-technology-education", "official_site", "NEMSU CITE", 1, "academics"),
    SourceSeed("https://www.nemsu.edu.ph/academics/colleges/college-of-law", "official_site", "NEMSU College of Law", 1, "academics"),
    SourceSeed("https://www.nemsu.edu.ph/academics/colleges/college-of-teacher-education", "official_site", "NEMSU CTE", 1, "academics"),
    SourceSeed("https://www.nemsu.edu.ph/academics/colleges/collge-of-arts-and-sciences", "official_site", "NEMSU CAS", 1, "academics"),
    SourceSeed("https://www.nemsu.edu.ph/academics/colleges/graduate-studies", "official_site", "NEMSU Graduate Studies", 1, "academics"),
    SourceSeed("https://www.nemsu.edu.ph/news/THEY-HAVE-CONQUERED-THE-BAR-EXAMS", "official_site", "NEMSU News - Bar Exams", 1, "news"),
    SourceSeed("https://www.nemsu.edu.ph/news/Training-on-Thesis-Dissertation-Advising", "official_site", "NEMSU News - Thesis Training", 1, "news"),
    SourceSeed("https://www.nemsu.edu.ph/news/Ground-Breaking-College-of-Medicine", "official_site", "NEMSU News - College of Medicine", 1, "news"),
    SourceSeed("https://www.nemsu.edu.ph/news/Reaffirmation-of-commitment-to-innovation-and-sustainable-development", "official_site", "NEMSU News - Innovation Commitment", 1, "news"),
    SourceSeed("https://nemsu.edu.ph/news/Institutional-Matters-F.Y.2025", "official_site", "NEMSU News - Institutional Matters FY2025", 1, "news"),
)

PORTAL_SEEDS: tuple[SourceSeed, ...] = (
    SourceSeed("https://preenrollment.nemsu.edu.ph", "official_portal", "NEMSU MyPortal", 1, "online_service", crawl=False),
    SourceSeed("https://lms.nemsu.edu.ph", "official_portal", "NEMSU LMS", 1, "online_service", crawl=False),
    SourceSeed("https://erms.nemsu.edu.ph", "official_portal", "NEMSU ERMS", 1, "online_service", crawl=False),
    SourceSeed("https://csms.nemsu.edu.ph", "official_portal", "NEMSU CSMS", 1, "online_service", crawl=False),
    SourceSeed("https://dts.nemsu.edu.ph", "official_portal", "NEMSU DTS", 1, "online_service", crawl=False),
    SourceSeed("https://itinero.nemsu.edu.ph/", "official_portal", "NEMSU Itinero", 1, "online_service", crawl=False),
    SourceSeed("https://epass.nemsu.edu.ph/login", "official_portal", "NEMSU ePass", 1, "online_service", crawl=False),
    SourceSeed("https://smrj.nemsu.edu.ph/", "official_portal", "NEMSU SMRJ", 1, "online_service", crawl=False),
    SourceSeed("https://memo.nemsu.edu.ph/", "official_portal", "NEMSU Memo", 1, "online_service", crawl=False),
)

FACEBOOK_SEEDS: tuple[SourceSeed, ...] = (
    SourceSeed("https://www.facebook.com/nemsuofficialph", "official_facebook", "NEMSU Official Facebook", 2, "social", crawl=False),
    SourceSeed("https://www.facebook.com/nemsucagwaitcampus", "official_facebook", "NEMSU Cagwait Campus Facebook", 2, "social", crawl=False),
    SourceSeed("https://www.facebook.com/nemsusanmiguel", "official_facebook", "NEMSU San Miguel Facebook", 2, "social", crawl=False),
    SourceSeed("https://www.facebook.com/nemsuliangacampus", "official_facebook", "NEMSU Lianga Campus Facebook", 2, "social", crawl=False),
    SourceSeed("https://www.facebook.com/nemsubisligofficial", "official_facebook", "NEMSU Bislig Campus Facebook", 2, "social", crawl=False),
    SourceSeed("https://www.facebook.com/profile.php?id=100087947334279", "legacy_facebook", "Legacy NEMSU/SDSSU Facebook Source", 5, "social", crawl=False),
    SourceSeed("https://www.facebook.com/profile.php?id=100084488606304", "legacy_facebook", "Legacy NEMSU/SDSSU Facebook Source", 5, "social", crawl=False),
    SourceSeed("https://www.facebook.com/sdssutc", "legacy_facebook", "SDSSU Tandag Campus Facebook", 5, "social", crawl=False),
    SourceSeed("https://www.facebook.com/SDSSUSanMigCampus", "legacy_facebook", "SDSSU San Miguel Facebook", 5, "social", crawl=False),
    SourceSeed("https://www.facebook.com/profile.php?id=61584336309531", "legacy_facebook", "Legacy NEMSU Facebook Source", 5, "social", crawl=False),
    SourceSeed("https://www.facebook.com/NEMSUTandagUSG", "student_facebook", "NEMSU Tandag USG", 3, "student_affairs", crawl=False),
    SourceSeed("https://www.facebook.com/nemsuliangassg", "student_facebook", "NEMSU Lianga SSG", 3, "student_affairs", crawl=False),
    SourceSeed("https://www.facebook.com/NEMSUCantilanSSG", "student_facebook", "NEMSU Cantilan SSG", 3, "student_affairs", crawl=False),
    SourceSeed("https://www.facebook.com/SSGLegislative", "student_facebook", "NEMSU Student Legislative", 3, "student_affairs", crawl=False),
    SourceSeed("https://www.facebook.com/officialSUEU", "student_facebook", "SUEU Official", 3, "student_affairs", crawl=False),
    SourceSeed("https://www.facebook.com/CITEACSS", "student_facebook", "CITE ACSS", 3, "student_affairs", crawl=False),
    SourceSeed("https://www.facebook.com/thevanguardmagazinenemsumain", "student_facebook", "The Vanguard Magazine", 3, "student_publication", crawl=False),
)

SCHOLARSHIP_SEEDS: tuple[SourceSeed, ...] = (
    SourceSeed("https://unifast.gov.ph/", "government_site", "UniFAST", 1, "scholarship"),
    SourceSeed("https://unifast.gov.ph/tes.html", "government_site", "UniFAST TES", 1, "scholarship"),
    SourceSeed("https://unifast.gov.ph/fhe.html", "government_site", "UniFAST Free Higher Education", 1, "scholarship"),
    SourceSeed("https://ched.gov.ph/sikap/", "government_site", "CHED SIKAP", 1, "scholarship"),
    SourceSeed("https://ched.gov.ph/msrs/", "government_site", "CHED MSRS", 1, "scholarship"),
    SourceSeed("https://ched.gov.ph/mtpsp/", "government_site", "CHED MTP-SP", 1, "scholarship"),
    SourceSeed("https://ched.gov.ph/scholarship-program-for-coconut-farmers-and-their-families-coscho-for-ay-2024-2025/", "government_site", "CHED CoScho", 1, "scholarship"),
    SourceSeed("https://caraga.ched.gov.ph/scholarship-program-for-coconut-farmers-and-their-families/", "government_site", "CHED Caraga CoScho", 1, "scholarship"),
    SourceSeed("https://www.science-scholarships.ph/pdf/2026_UG_Scholarship_Brochure.pdf", "government_site", "DOST-SEI Science Scholarships Brochure", 1, "scholarship"),
    SourceSeed("https://owwa.gov.ph/wp-content/uploads/2025/03/OWWA_CC_021225-updated.pdf", "government_site", "OWWA Scholarship Citizen Charter", 1, "scholarship"),
)

ALL_SEEDS = OFFICIAL_SITE_SEEDS + PORTAL_SEEDS + FACEBOOK_SEEDS + SCHOLARSHIP_SEEDS

CAMPUS_ALIASES = {
    "Tandag": {"tandag", "main campus", "nemsu main", "nemsu tandag"},
    "Cantilan": {"cantilan", "nemsu cantilan"},
    "San Miguel": {"san miguel", "nemsu san miguel"},
    "Cagwait": {"cagwait", "nemsu cagwait"},
    "Lianga": {"lianga", "nemsu lianga"},
    "Tagbina": {"tagbina", "nemsu tagbina"},
    "Bislig": {"bislig", "nemsu bislig"},
}

COLLEGE_ALIASES = {
    "College of Business and Management": ("CBM",),
    "College of Engineering and Technology": ("COET", "COE"),
    "College of Information Technology Education": ("CITE",),
    "College of Law": (),
    "College of Teacher Education": ("CTE",),
    "College of Arts and Sciences": ("CAS",),
    "Graduate Studies": ("GS",),
}

INSTITUTION_ALIASES = (
    ("North Eastern Mindanao State University", ("NEMSU", "Northeastern Mindanao State University"), "current_official_name"),
    ("Surigao del Sur State University", ("SDSSU",), "former_official_name"),
    ("Surigao del Sur Polytechnic State College", ("SSPSC",), "former_official_name"),
    ("Surigao del Sur Polytechnic College", ("SSPC",), "former_official_name"),
    ("Bukidnon External Studies Center", ("BESC",), "predecessor"),
)

OFFICE_HINTS = (
    "Guidance",
    "Registrar",
    "Library",
    "Admissions",
    "Student Affairs",
    "Research and Development",
    "Extension Services",
    "Public Information",
    "Human Resource",
    "Cashier",
    "Procurement",
    "Budget",
    "Legal",
    "International Affairs",
)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _chunked(rows: list[dict[str, Any]], size: int = _BATCH_SIZE) -> Iterable[list[dict[str, Any]]]:
    for index in range(0, len(rows), size):
        yield rows[index : index + size]


def _normalize_name(value: str) -> str:
    return normalize_text_for_match(value).replace("collge", "college")


def _clean_optional(value: Any) -> str | None:
    cleaned = clean_text_block(str(value or ""))
    return cleaned or None


def _base_url(url: str) -> str:
    return normalize_url(url, preserve_query=False)


def _source_id(seed: SourceSeed) -> str:
    return stable_id("source", seed.source_type, _base_url(seed.url), seed.source_name)


def _is_document_url(url: str) -> bool:
    lower = url.lower()
    return lower.endswith((".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv", ".txt")) or urlparse(url).netloc.lower() in _DOCUMENT_DOMAINS


def _extract_main_text(html: str) -> str:
    text = trafilatura.extract(
        html,
        include_links=True,
        include_tables=True,
        include_formatting=False,
        favor_recall=True,
    )
    if text:
        return clean_text_block(text)
    soup = BeautifulSoup(html, "lxml")
    for tag in soup.select("script,style,noscript,header,footer,nav,form,.navbar,.footer,.pagination,.social"):
        tag.decompose()
    return clean_text_block((soup.body or soup).get_text("\n", strip=True))


def _extract_meta_date(soup: BeautifulSoup) -> str | None:
    for attrs in (
        {"property": "article:published_time"},
        {"property": "article:modified_time"},
        {"property": "og:updated_time"},
        {"name": "pubdate"},
    ):
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            parsed = parse_date(tag["content"])
            if parsed:
                return parsed
    time_tag = soup.find("time")
    if time_tag:
        return parse_date(time_tag.get("datetime") or time_tag.get_text(" ", strip=True))
    return None


def _guess_campus(*values: str | None) -> str | None:
    haystack = normalize_text_for_match(" ".join(value or "" for value in values))
    for campus, aliases in CAMPUS_ALIASES.items():
        if any(alias in haystack for alias in aliases):
            return campus
    return None


def _guess_office(*values: str | None) -> str | None:
    haystack = " ".join(value or "" for value in values)
    for office in OFFICE_HINTS:
        if office.lower() in haystack.lower():
            return office
    return None


def _guess_document_type(url: str, title: str, text: str) -> str:
    lowered = f"{url} {title} {text[:500]}".lower()
    if "/news" in lowered or "news" in title.lower():
        return "news"
    if "/announcements" in lowered or "announcement" in lowered or "advisory" in lowered:
        return "announcement"
    if "/events" in lowered or "event" in title.lower():
        return "event"
    if "/jobs" in lowered or "job" in lowered or "hiring" in lowered:
        return "job_posting"
    if "/bac-matters" in lowered or "bidding" in lowered or "procurement" in lowered:
        return "procurement"
    if "/citizens-charter" in lowered:
        return "citizens_charter"
    if "/transparency-seal" in lowered:
        return "transparency"
    if "/directory" in lowered:
        return "directory"
    if "/programs" in lowered or "program" in title.lower():
        return "programs"
    if any(item in lowered for item in ("/guidance", "/registrar", "/library", "/admission", "/enrolment")):
        return "student_service"
    if "scholarship" in lowered or "tes" in lowered or "free higher education" in lowered:
        return "scholarship"
    if "mission" in lowered and "vision" in lowered:
        return "institution_profile"
    if _is_document_url(url):
        return "external_document"
    return "page"


def _iter_paragraphs(text: str) -> list[str]:
    return [clean_text_block(item) for item in re.split(r"\n{2,}", text or "") if len(clean_text_block(item)) >= 80]


def _extract_emails(text: str) -> list[str]:
    return sorted(set(_EMAIL_RE.findall(text or "")))


def _extract_phones(text: str) -> list[str]:
    phones = [clean_text_block(item) for item in _PHONE_RE.findall(text or "")]
    return sorted({item for item in phones if len(re.sub(r"\D", "", item)) >= 7})


def _degree_level(program_name: str) -> str | None:
    lowered = program_name.lower()
    if "doctor" in lowered or lowered.startswith(("phd", "edd")):
        return "doctorate"
    if "master" in lowered or lowered.startswith(("ms", "ma")):
        return "master"
    if "juris doctor" in lowered or "law" in lowered:
        return "professional"
    if "diploma" in lowered or "certificate" in lowered:
        return "diploma"
    if "bachelor" in lowered or lowered.startswith(("bs", "ba", "beed", "bsed", "btvted", "btled")):
        return "bachelor"
    return None


def _extract_program_rows(soup: BeautifulSoup, source_url: str) -> list[dict[str, Any]]:
    programs: list[dict[str, Any]] = []
    for table in soup.find_all("table"):
        rows = [
            [clean_text_block(cell.get_text(" ", strip=True)) for cell in tr.find_all(["th", "td"])]
            for tr in table.find_all("tr")
        ]
        rows = [row for row in rows if any(row)]
        if len(rows) < 3:
            continue
        college = clean_text_block(rows[0][0]) if rows[0] else ""
        if not college:
            continue
        if college.lower().startswith("collge"):
            college = "College of Arts and Sciences"
        for row in rows[2:]:
            program_name = clean_text_block(row[0]) if row else ""
            if not program_name or not _PROGRAM_RE.search(program_name):
                continue
            accreditation = clean_text_block(row[1]) if len(row) > 1 else ""
            campus = _guess_campus(college, program_name)
            programs.append(
                {
                    "id": stable_id("program", college, campus or "", program_name, source_url),
                    "campus": campus,
                    "college": college,
                    "program_name": program_name,
                    "normalized_program_name": _normalize_name(program_name),
                    "degree_level": _degree_level(program_name),
                    "accreditation": accreditation or None,
                    "source_url": source_url,
                    "metadata": {"extracted_from": "table"},
                }
            )
    return programs


def _extract_contacts_from_directory(soup: BeautifulSoup, source_url: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    contacts: list[dict[str, Any]] = []
    offices: dict[str, dict[str, Any]] = {}
    table = soup.find("table")
    if table is None:
        return contacts, []
    for tr in table.find_all("tr"):
        cells = [clean_text_block(td.get_text(" ", strip=True)) for td in tr.find_all(["th", "td"])]
        if len(cells) < 2 or cells[0].lower() == "name":
            continue
        name, title = cells[0], cells[1]
        phone = cells[2] if len(cells) > 2 and cells[2] not in {"", "-"} else None
        email = cells[3] if len(cells) > 3 and cells[3] not in {"", "-"} else None
        office = _guess_office(title)
        campus = _guess_campus(title, name)
        contacts.append(
            {
                "id": stable_id("contact", name, title, office or "", campus or "", source_url),
                "name": name,
                "title": title or None,
                "office": office,
                "campus": campus,
                "phone": phone,
                "email": email,
                "source_url": source_url,
                "metadata": {"public_visibility": "public"},
                "last_seen_at": _now_iso(),
            }
        )
        if office:
            offices.setdefault(
                f"{office}|{campus or ''}",
                {
                    "id": stable_id("office", office, campus or "", source_url),
                    "office_name": office,
                    "normalized_office_name": _normalize_name(office),
                    "campus": campus,
                    "description": None,
                    "contact_email": email,
                    "contact_phone": phone,
                    "source_url": source_url,
                    "metadata": {"derived_from": "directory"},
                },
            )
    return contacts, list(offices.values())


def _extract_news_row(doc: FetchedDocument) -> dict[str, Any] | None:
    if doc.document_type not in {"news", "announcement", "event", "job_posting", "procurement"}:
        return None
    if len(doc.cleaned_text) < 120:
        return None
    return {
        "id": stable_id("news", doc.canonical_url, doc.title),
        "title": doc.title,
        "normalized_title": _normalize_name(doc.title),
        "summary": summarize_text(doc.cleaned_text, max_words=60),
        "body": doc.cleaned_text[:12000],
        "campus": doc.campus,
        "category": doc.document_type,
        "published_at": doc.published_at,
        "source_id": doc.source_id,
        "source_url": doc.canonical_url,
        "metadata": {"trust_tier": doc.trust_tier, "source_type": doc.source_type, "public_visibility": "public"},
    }


def _extract_scholarship_rows(doc: FetchedDocument) -> list[dict[str, Any]]:
    if doc.document_type != "scholarship" and doc.category != "scholarship":
        return []
    name = clean_text_block(doc.title)
    provider = doc.source_name
    lowered = name.lower()
    if "tes" in lowered:
        name, provider = "Tertiary Education Subsidy (TES)", "UniFAST"
    elif "free higher education" in lowered or "fhe" in lowered:
        name, provider = "Free Higher Education", "UniFAST"
    elif "merit scholarship" in lowered:
        provider = "CHED"
    elif "stufaps" in lowered:
        provider = "CHED"
    elif "science scholarships" in lowered:
        name, provider = "DOST-SEI Science Scholarships", "DOST-SEI"
    elif "owwa" in lowered:
        provider = "OWWA"
    eligibility = None
    benefits = None
    for paragraph in _iter_paragraphs(doc.cleaned_text)[:10]:
        lower = paragraph.lower()
        if eligibility is None and any(token in lower for token in ("eligibility", "eligible", "qualified", "applicant")):
            eligibility = paragraph
        if benefits is None and any(token in lower for token in ("benefit", "allowance", "grant", "financial")):
            benefits = paragraph
    return [
        {
            "id": stable_id("scholarship", name, provider, doc.canonical_url),
            "scholarship_name": name,
            "normalized_scholarship_name": _normalize_name(name),
            "provider": provider,
            "provider_type": "government",
            "applies_to_nemsu_students": True,
            "eligibility_text": eligibility,
            "benefits_text": benefits,
            "application_url": doc.canonical_url,
            "source_url": doc.canonical_url,
            "metadata": {"source_type": doc.source_type, "trust_tier": doc.trust_tier, "document_title": doc.title},
        }
    ]


class StructuredNEMSUIngestor:
    def __init__(self, client: SupabasePersistenceClient, *, max_pages: int = 180, timeout_seconds: float = 20.0) -> None:
        self._client = client
        self._max_pages = max(20, max_pages)
        self._timeout_seconds = timeout_seconds
        self._robots: dict[str, robotparser.RobotFileParser] = {}
        self._seen_urls: set[str] = set()
        self._last_requested: dict[str, float] = {}

    def _seed_rows(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for seed in ALL_SEEDS:
            rows.append(
                {
                    "id": _source_id(seed),
                    "source_type": seed.source_type,
                    "source_name": seed.source_name,
                    "base_url": _base_url(seed.url),
                    "trust_tier": seed.trust_tier,
                    "category": seed.category,
                    "active": True,
                    "metadata": {"seed_url": seed.url, "crawl_enabled": seed.crawl, "last_seen_date": datetime.now(UTC).date().isoformat()},
                }
            )
        return rows

    def _robots_allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        parser = self._robots.get(base)
        if parser is None:
            parser = robotparser.RobotFileParser()
            try:
                response = httpx.get(f"{base}/robots.txt", headers=_HTTP_HEADERS, follow_redirects=True, timeout=self._timeout_seconds)
                parser.parse(response.text.splitlines())
            except Exception:
                return True
            self._robots[base] = parser
        return parser.can_fetch(_HTTP_HEADERS["User-Agent"], url)

    def _delay(self, domain: str) -> None:
        now = datetime.now(UTC).timestamp()
        last = self._last_requested.get(domain)
        if last is not None and now - last < 0.5:
            time.sleep(0.5 - (now - last))
        self._last_requested[domain] = datetime.now(UTC).timestamp()

    @staticmethod
    def _extract_binary(response: httpx.Response, final_url: str) -> str:
        content_type = (response.headers.get("content-type") or "").lower()
        if "pdf" in content_type or final_url.lower().endswith(".pdf"):
            try:
                reader = PdfReader(io.BytesIO(response.content))
                return "\n\n".join(
                    clean_text_block(page.extract_text() or "")
                    for page in reader.pages
                    if clean_text_block(page.extract_text() or "")
                )
            except Exception:
                return ""
        try:
            return response.text
        except UnicodeDecodeError:
            return ""

    def _fetch(self, http: httpx.Client, seed: SourceSeed, url: str, parent_url: str | None = None) -> tuple[FetchedDocument | None, list[str], list[str]]:
        normalized = normalize_url(url, base_url=seed.url, preserve_query=urlparse(url).netloc.lower() in _DOCUMENT_DOMAINS)
        if normalized in self._seen_urls or _SKIP_URL_RE.search(normalized) or not self._robots_allowed(normalized):
            return None, [], []
        self._seen_urls.add(normalized)
        self._delay(urlparse(normalized).netloc.lower())
        headers = _HTTP_HEADERS if urlparse(normalized).netloc.lower() in _NEMSU_DOMAINS else _BROWSER_HEADERS
        try:
            response = http.get(normalized, headers=headers, follow_redirects=True, timeout=self._timeout_seconds)
            response.raise_for_status()
        except Exception as exc:
            logger.warning("Failed fetching %s (%s)", normalized, exc)
            return None, [], []
        final_url = normalize_url(str(response.url), preserve_query=urlparse(str(response.url)).netloc.lower() in _DOCUMENT_DOMAINS)
        if _is_document_url(final_url):
            raw_text = self._extract_binary(response, final_url)
            cleaned = clean_text_block(raw_text)
            if len(cleaned) < 80:
                return None, [], []
            return (
                FetchedDocument(
                    canonical_url=final_url,
                    source_id=_source_id(seed),
                    source_type=seed.source_type,
                    source_name=seed.source_name,
                    trust_tier=seed.trust_tier,
                    category=seed.category,
                    title=final_url.rsplit("/", 1)[-1] or seed.source_name,
                    document_type="external_document",
                    campus=_guess_campus(final_url, cleaned[:800]),
                    office=_guess_office(cleaned[:800]),
                    published_at=None,
                    raw_text=raw_text,
                    cleaned_text=cleaned,
                    html=None,
                    metadata={"parent_url": parent_url, "resolved_url": final_url},
                ),
                [],
                [],
            )

        html = response.text
        title = ""
        page_links: list[str] = []
        document_links: list[str] = []
        try:
            soup = BeautifulSoup(html, "lxml")
            title = clean_text_block((soup.title.get_text(" ", strip=True) if soup.title else "") or seed.source_name or final_url)
            for anchor in soup.find_all("a", href=True):
                candidate = normalize_url(anchor["href"], base_url=final_url, preserve_query="facebook.com" in anchor["href"])
                domain = urlparse(candidate).netloc.lower()
                if domain in _NEMSU_DOMAINS:
                    page_links.append(candidate)
                elif domain in _DOCUMENT_DOMAINS or _is_document_url(candidate):
                    document_links.append(candidate)
        except Exception:
            soup = None
        raw_text = _extract_main_text(html)
        cleaned = clean_text_block(raw_text)
        if len(cleaned) < 80 and urlparse(final_url).netloc.lower() in _NEMSU_DOMAINS:
            return None, [], []
        return (
            FetchedDocument(
                canonical_url=final_url,
                source_id=_source_id(seed),
                source_type=seed.source_type,
                source_name=seed.source_name,
                trust_tier=seed.trust_tier,
                category=seed.category,
                title=title or seed.source_name,
                document_type=_guess_document_type(final_url, title or seed.source_name, cleaned),
                campus=_guess_campus(final_url, title, cleaned[:1000]),
                office=_guess_office(final_url, title, cleaned[:800]),
                published_at=_extract_meta_date(soup) if soup else None,
                raw_text=raw_text,
                cleaned_text=cleaned,
                html=html,
                metadata={"parent_url": parent_url, "resolved_url": final_url},
            ),
            list(dict.fromkeys(page_links)),
            list(dict.fromkeys(document_links)),
        )

    def _crawl_documents(self) -> list[FetchedDocument]:
        docs: list[FetchedDocument] = []
        queue: deque[tuple[SourceSeed, str, str | None]] = deque((seed, seed.url, None) for seed in OFFICIAL_SITE_SEEDS + SCHOLARSHIP_SEEDS)
        with httpx.Client(follow_redirects=True, timeout=self._timeout_seconds) as http:
            while queue and len(docs) < self._max_pages:
                seed, url, parent_url = queue.popleft()
                doc, page_links, document_links = self._fetch(http, seed, url, parent_url)
                if doc is not None:
                    docs.append(doc)
                for link in page_links[:20]:
                    if len(queue) + len(docs) >= self._max_pages:
                        break
                    queue.append((seed, link, doc.canonical_url if doc else parent_url))
                for link in document_links[:6]:
                    if len(queue) + len(docs) >= self._max_pages:
                        break
                    queue.append((seed, link, doc.canonical_url if doc else parent_url))
        deduped: list[FetchedDocument] = []
        seen: set[str] = set()
        fingerprints: set[str] = set()
        for doc in docs:
            fingerprint = f"{sha256_text(doc.cleaned_text)}|{_normalize_name(doc.title)}"
            if doc.canonical_url in seen or fingerprint in fingerprints:
                continue
            seen.add(doc.canonical_url)
            fingerprints.add(fingerprint)
            deduped.append(doc)
        return deduped

    def _facebook_sources_and_docs(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        source_rows: list[dict[str, Any]] = []
        doc_rows: list[dict[str, Any]] = []
        with httpx.Client(follow_redirects=True, timeout=self._timeout_seconds, headers=_FB_HEADERS) as http:
            for seed in FACEBOOK_SEEDS:
                title = None
                description = None
                page_id = None
                status = "limited"
                try:
                    response = http.get(seed.url)
                    response.raise_for_status()
                    soup = BeautifulSoup(response.text, "lxml")
                    title_tag = soup.find("meta", attrs={"property": "og:title"})
                    desc_tag = soup.find("meta", attrs={"property": "og:description"})
                    app_url = soup.find("meta", attrs={"property": "al:android:url"})
                    title = clean_text_block(title_tag.get("content", "")) if title_tag else None
                    description = clean_text_block(desc_tag.get("content", "")) if desc_tag else None
                    if app_url and app_url.get("content"):
                        match = re.search(r"profile/(\d+)", app_url["content"])
                        if match:
                            page_id = match.group(1)
                    if title:
                        status = "identity_verified"
                except Exception as exc:
                    logger.warning("Facebook probe failed %s (%s)", seed.url, exc)
                    status = "unreachable"
                source_rows.append(
                    {
                        "id": _source_id(seed),
                        "source_type": seed.source_type,
                        "source_name": seed.source_name,
                        "base_url": _base_url(seed.url),
                        "trust_tier": seed.trust_tier,
                        "category": seed.category,
                        "active": True,
                        "metadata": {
                            "seed_url": seed.url,
                            "facebook_page_title": title,
                            "facebook_page_id": page_id,
                            "fetch_status": status,
                            "public_post_scrape": "limited_without_account_dependent_behavior",
                        },
                    }
                )
                if title:
                    body = clean_text_block("\n".join(item for item in (title, description or "") if item))
                    doc_rows.append(
                        {
                            "id": stable_id("doc", seed.url, title),
                            "source_id": _source_id(seed),
                            "canonical_url": seed.url,
                            "title": title,
                            "document_type": "facebook_page_profile",
                            "campus": _guess_campus(title, description or ""),
                            "office": None,
                            "published_at": None,
                            "scraped_at": _now_iso(),
                            "raw_text": body,
                            "cleaned_text": body,
                            "content_hash": sha256_text(body),
                            "metadata": {"source_type": seed.source_type, "fetch_status": status, "public_visibility": "limited_public_metadata"},
                            "public_visibility": "limited_public_metadata",
                            "last_seen_at": _now_iso(),
                        }
                    )
        return source_rows, doc_rows

    def _upsert_many(self, table: str, rows: list[dict[str, Any]], *, on_conflict: str) -> int:
        if not rows:
            return 0
        for batch in _chunked(rows):
            self._client.upsert(table, batch, on_conflict=on_conflict, returning="minimal")
        return len(rows)

    def _replace_chunks(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        document_ids = sorted({str(row.get("document_id") or "").strip() for row in rows if str(row.get("document_id") or "").strip()})
        for document_id in document_ids:
            self._client.delete("kb_chunks", filters={"document_id": document_id}, returning="minimal")
        for batch in _chunked(rows):
            self._client.upsert("kb_chunks", batch, on_conflict="chunk_id", returning="minimal")
        return len(rows)

    def _build_document_rows(self, docs: list[FetchedDocument]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for doc in docs:
            rows.append(
                {
                    "id": stable_id("doc", doc.canonical_url, doc.document_type),
                    "source_id": doc.source_id,
                    "canonical_url": doc.canonical_url,
                    "title": doc.title,
                    "document_type": doc.document_type,
                    "campus": doc.campus,
                    "office": doc.office,
                    "published_at": doc.published_at,
                    "scraped_at": _now_iso(),
                    "raw_text": doc.raw_text[:100000],
                    "cleaned_text": doc.cleaned_text[:100000],
                    "content_hash": sha256_text(doc.cleaned_text),
                    "metadata": {**doc.metadata, "source_name": doc.source_name, "source_type": doc.source_type, "trust_tier": doc.trust_tier, "category": doc.category},
                    "public_visibility": "public",
                    "last_seen_at": _now_iso(),
                }
            )
        return rows

    def _build_chunk_rows(self, docs: list[FetchedDocument]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for doc in docs:
            document_id = stable_id("doc", doc.canonical_url, doc.document_type)
            paragraphs = _iter_paragraphs(doc.cleaned_text) or [doc.cleaned_text[:2500]]
            for index, paragraph in enumerate(paragraphs, start=1):
                if len(paragraph) < 60:
                    continue
                rows.append(
                    {
                        "chunk_id": stable_id("chunk", document_id, str(index)),
                        "document_id": document_id,
                        "chunk_index": index,
                        "token_estimate": approx_token_count(paragraph),
                        "source_kind": "document",
                        "source_ref": document_id,
                        "page_id": None,
                        "title": doc.title,
                        "url": doc.canonical_url,
                        "heading_path": [],
                        "page_type": doc.document_type,
                        "topic": doc.category or doc.document_type,
                        "content": paragraph,
                        "normalized_text": normalize_text_for_match(paragraph),
                        "short_summary": summarize_text(paragraph, max_words=40),
                        "keywords": [],
                        "entity_ids": [],
                        "publication_date": doc.published_at,
                        "updated_date": _now_iso(),
                        "freshness": "current" if doc.document_type in {"news", "announcement", "event"} else "evergreen",
                        "content_hash": sha256_text(paragraph),
                        "previous_chunk_id": None,
                        "next_chunk_id": None,
                        "parent_chunk_id": None,
                        "source_section_id": None,
                        "metadata": {"document_type": doc.document_type, "campus": doc.campus, "office": doc.office, "source_type": doc.source_type},
                    }
                )
        return rows

    def _build_entities_and_aliases(self, docs: list[FetchedDocument]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        entities: dict[str, dict[str, Any]] = {}
        aliases: dict[tuple[str, str], dict[str, Any]] = {}
        for name, alias_values, status in INSTITUTION_ALIASES:
            entity_id = stable_id("entity", "institution", name)
            entities[entity_id] = {"entity_id": entity_id, "canonical_name": name, "entity_type": "institution", "description": None, "campus": None, "title": None, "content": None, "source_urls": ["https://www.nemsu.edu.ph/aboutus"], "metadata": {"status": status}}
            for alias in alias_values:
                aliases[(entity_id, _normalize_name(alias))] = {"entity_id": entity_id, "canonical_name": name, "alias": alias, "normalized_alias": _normalize_name(alias)}
        for campus, alias_values in CAMPUS_ALIASES.items():
            entity_id = stable_id("entity", "campus", campus)
            entities[entity_id] = {"entity_id": entity_id, "canonical_name": campus, "entity_type": "campus", "description": f"NEMSU {campus} Campus", "campus": campus, "title": None, "content": None, "source_urls": [], "metadata": {}}
            for alias in alias_values:
                aliases[(entity_id, _normalize_name(alias))] = {"entity_id": entity_id, "canonical_name": campus, "alias": alias, "normalized_alias": _normalize_name(alias)}
        for college, alias_values in COLLEGE_ALIASES.items():
            entity_id = stable_id("entity", "college", college)
            entities[entity_id] = {"entity_id": entity_id, "canonical_name": college, "entity_type": "college", "description": college, "campus": None, "title": None, "content": None, "source_urls": [], "metadata": {}}
            for alias in alias_values:
                aliases[(entity_id, _normalize_name(alias))] = {"entity_id": entity_id, "canonical_name": college, "alias": alias, "normalized_alias": _normalize_name(alias)}
        for seed in PORTAL_SEEDS:
            name = seed.source_name.replace("NEMSU ", "").strip()
            entity_id = stable_id("entity", "online_service", name)
            entities[entity_id] = {"entity_id": entity_id, "canonical_name": name, "entity_type": "online_service", "description": f"Official NEMSU online service: {name}", "campus": None, "title": seed.source_name, "content": f"{seed.source_name} is available at {seed.url}.", "source_urls": [seed.url], "metadata": {"service_url": seed.url, "trust_tier": seed.trust_tier}}
            aliases[(entity_id, _normalize_name(name))] = {"entity_id": entity_id, "canonical_name": name, "alias": name, "normalized_alias": _normalize_name(name)}
        for doc in docs:
            if doc.campus:
                entity_id = stable_id("entity", "campus", doc.campus)
                if doc.canonical_url not in entities[entity_id]["source_urls"]:
                    entities[entity_id]["source_urls"].append(doc.canonical_url)
        return list(entities.values()), list(aliases.values())

    def run(self) -> dict[str, Any]:
        if not self._client.configured:
            raise RuntimeError("Supabase is not configured.")
        try:
            self._client.select("kb_sources", limit=1)
            self._client.select("kb_documents", limit=1)
        except PersistenceError as exc:
            raise RuntimeError(
                "Structured KB tables are not available in Supabase. Apply "
                "supabase/migrations/202604140004_nemsu_structured_kb.sql first."
            ) from exc
        seed_rows = self._seed_rows()
        self._upsert_many("kb_sources", seed_rows, on_conflict="base_url")

        docs = self._crawl_documents()
        fb_sources, fb_docs = self._facebook_sources_and_docs()
        if fb_sources:
            self._upsert_many("kb_sources", fb_sources, on_conflict="base_url")

        document_rows = self._build_document_rows(docs)
        chunk_rows = self._build_chunk_rows(docs)
        entity_rows, alias_rows = self._build_entities_and_aliases(docs)
        campus_rows = [
            {"id": stable_id("campus", campus), "campus_name": campus, "normalized_name": _normalize_name(campus), "short_name": campus, "location": None, "description": f"NEMSU {campus} Campus", "source_url": "https://www.nemsu.edu.ph/aboutus", "metadata": {"aliases": sorted(values)}}
            for campus, values in CAMPUS_ALIASES.items()
        ]
        college_rows = [
            {"id": stable_id("college", college), "college_name": college, "normalized_name": _normalize_name(college), "abbreviation": aliases[0] if aliases else None, "campus": None, "description": None, "source_url": "", "metadata": {"aliases": list(aliases)}}
            for college, aliases in COLLEGE_ALIASES.items()
        ]
        program_rows: dict[str, dict[str, Any]] = {}
        contact_rows: dict[str, dict[str, Any]] = {}
        office_rows: dict[str, dict[str, Any]] = {}
        news_rows: dict[str, dict[str, Any]] = {}
        scholarship_rows: dict[str, dict[str, Any]] = {}
        for doc in docs:
            if doc.html and doc.document_type == "programs":
                for row in _extract_program_rows(BeautifulSoup(doc.html, "lxml"), doc.canonical_url):
                    program_rows[row["id"]] = row
            if doc.html and doc.document_type == "directory":
                contacts, offices = _extract_contacts_from_directory(BeautifulSoup(doc.html, "lxml"), doc.canonical_url)
                for row in contacts:
                    contact_rows[row["id"]] = row
                for row in offices:
                    office_rows[row["id"]] = row
            news_row = _extract_news_row(doc)
            if news_row is not None:
                news_rows[news_row["id"]] = news_row
            for row in _extract_scholarship_rows(doc):
                scholarship_rows[row["id"]] = row
            if doc.office:
                office_rows.setdefault(
                    stable_id("office", doc.office, doc.campus or "", doc.canonical_url),
                    {
                        "id": stable_id("office", doc.office, doc.campus or "", doc.canonical_url),
                        "office_name": doc.office,
                        "normalized_office_name": _normalize_name(doc.office),
                        "campus": doc.campus,
                        "description": summarize_text(doc.cleaned_text, max_words=100),
                        "contact_email": (_extract_emails(doc.cleaned_text) or [None])[0],
                        "contact_phone": (_extract_phones(doc.cleaned_text) or [None])[0],
                        "source_url": doc.canonical_url,
                        "metadata": {"document_type": doc.document_type},
                    },
                )

        counts = {
            "sources": len({row["base_url"] for row in seed_rows}),
            "documents": self._upsert_many("kb_documents", document_rows + fb_docs, on_conflict="canonical_url"),
            "chunks": self._replace_chunks(chunk_rows),
            "entities": self._upsert_many("kb_entities", entity_rows, on_conflict="entity_id"),
            "aliases": self._upsert_many("kb_aliases", alias_rows, on_conflict="entity_id,normalized_alias"),
            "campuses": self._upsert_many("kb_campuses", campus_rows, on_conflict="id"),
            "colleges": self._upsert_many("kb_colleges", college_rows, on_conflict="id"),
            "programs": self._upsert_many("kb_programs", list(program_rows.values()), on_conflict="id"),
            "contacts": self._upsert_many("kb_contacts", list(contact_rows.values()), on_conflict="id"),
            "offices": self._upsert_many("kb_offices", list(office_rows.values()), on_conflict="id"),
            "news": self._upsert_many("kb_news", list(news_rows.values()), on_conflict="id"),
            "scholarships": self._upsert_many("kb_scholarships", list(scholarship_rows.values()), on_conflict="id"),
            "documents_crawled": len(docs),
            "facebook_sources_probed": len(FACEBOOK_SEEDS),
        }
        return counts


def import_structured_kb(*, max_pages: int = 180, timeout_seconds: float = 20.0) -> dict[str, Any]:
    ingestor = StructuredNEMSUIngestor(SupabasePersistenceClient(settings.supabase), max_pages=max_pages, timeout_seconds=timeout_seconds)
    return ingestor.run()


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest structured NEMSU knowledge-base data into Supabase.")
    parser.add_argument("--max-pages", type=int, default=180, help="Maximum number of pages/documents to crawl.")
    parser.add_argument("--timeout", type=float, default=20.0, help="Per-request timeout in seconds.")
    args = parser.parse_args()
    try:
        print(import_structured_kb(max_pages=args.max_pages, timeout_seconds=args.timeout))
    except Exception as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
