from __future__ import annotations

from rapidfuzz import fuzz

from .models import PageRecord


def deduplicate_pages(pages: list[PageRecord]) -> tuple[list[PageRecord], list[dict[str, str]]]:
    kept: list[PageRecord] = []
    duplicates: list[dict[str, str]] = []
    by_canonical: dict[str, PageRecord] = {}
    for page in pages:
        key = page.canonical_url or page.url
        existing = by_canonical.get(key)
        if existing:
            duplicates.append({"page_id": page.page_id, "duplicate_of": existing.page_id, "reason": "same canonical_url"})
            continue
        exact_match = next((candidate for candidate in kept if candidate.content_hash == page.content_hash), None)
        if exact_match:
            duplicates.append({"page_id": page.page_id, "duplicate_of": exact_match.page_id, "reason": "same content_hash"})
            continue
        fuzzy_match = next(
            (
                candidate
                for candidate in kept
                if candidate.title.lower() == page.title.lower()
                and fuzz.token_set_ratio(candidate.cleaned_main_body_text[:4000], page.cleaned_main_body_text[:4000]) >= 97
            ),
            None,
        )
        if fuzzy_match:
            duplicates.append({"page_id": page.page_id, "duplicate_of": fuzzy_match.page_id, "reason": "near duplicate"})
            continue
        by_canonical[key] = page
        kept.append(page)
    return kept, duplicates
