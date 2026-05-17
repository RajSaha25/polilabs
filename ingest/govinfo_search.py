"""GovInfo full-text search for AI-governance bill candidates.

Uses the api.govinfo.gov /search endpoint with a Solr-style query restricted
to the BILLS collection and the inclusion-criteria date range. Returns one hit
per (package_id, version) — callers deduplicate to unique bills.
"""
from __future__ import annotations

import os
import time
from typing import Iterator

import requests

SEARCH_URL = "https://api.govinfo.gov/search"

# Search net: every term that GovInfo can pre-filter on. We cast wider than the
# strict anchor set so that bills mentioning "generative AI" but not the
# literal phrase "artificial intelligence" still surface; the candidate
# scorer applies the anchor gate downstream.
SEARCH_TERMS = [
    '"artificial intelligence"',
    '"machine learning"',
    '"generative AI"',
    '"generative artificial intelligence"',
    '"frontier model"',
    '"automated decision systems"',
    '"automated decision system"',
    '"facial recognition"',
]


def build_query(start_date: str, end_date: str) -> str:
    terms_or = " OR ".join(SEARCH_TERMS)
    return (
        f"collection:(BILLS) AND "
        f"publishdate:range({start_date},{end_date}) AND "
        f"({terms_or})"
    )


def search(
    query: str,
    *,
    api_key: str | None = None,
    page_size: int = 100,
    sleep_s: float = 0.2,
    max_pages: int = 200,
) -> Iterator[dict]:
    """Paginate through GovInfo /search results, yielding one result dict at a time.

    Pagination via offsetMark per the GovInfo API.
    """
    api_key = api_key or os.environ["GOVINFO_API_KEY"]
    offset_mark = "*"
    pages = 0
    seen_total: int | None = None

    while True:
        body = {
            "query": query,
            "pageSize": page_size,
            "offsetMark": offset_mark,
            "sorts": [{"field": "publishdate", "sortOrder": "DESC"}],
            "historical": True,
            "resultLevel": "default",
        }
        r = requests.post(
            f"{SEARCH_URL}?api_key={api_key}",
            json=body,
            timeout=60,
        )
        r.raise_for_status()
        data = r.json()
        results = data.get("results") or []
        if seen_total is None:
            seen_total = data.get("count")

        if not results:
            return

        for item in results:
            yield item

        next_mark = data.get("offsetMark")
        if not next_mark or next_mark == offset_mark:
            return
        offset_mark = next_mark
        pages += 1
        if pages >= max_pages:
            return
        time.sleep(sleep_s)
