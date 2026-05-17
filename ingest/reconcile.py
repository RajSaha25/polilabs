"""Reconcile candidate bills with Congress.gov metadata.

Pulls per-bill metadata (title, sponsor, summary, subjects, latest action) and
caches it under data/cache/congress_gov/ so re-runs are instant.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from sources.congress_gov import CongressGov

from .candidate import Candidate

CACHE_DIR = Path("data/cache/congress_gov")


def _cache_path(congress: int, bill_type: str, number: int, kind: str) -> Path:
    return CACHE_DIR / f"{congress}-{bill_type}-{number}.{kind}.json"


def _fetch_cached(path: Path, fetcher) -> dict | None:
    """Fetch via `fetcher()` with on-disk JSON cache. Returns None on 404."""
    if path.exists():
        with open(path) as f:
            return json.load(f)
    try:
        data = fetcher()
    except Exception as e:
        # Surface error to caller via empty payload; record_error captures it.
        raise
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    return data


def reconcile_bill(
    client: CongressGov,
    candidate: Candidate,
    *,
    sleep_s: float = 0.05,
) -> None:
    """Populate Congress.gov fields on the candidate in place. Caches all responses."""
    congress = candidate.congress
    bill_type = candidate.bill_type
    number = candidate.bill_number

    try:
        # Main bill record
        bill_resp = _fetch_cached(
            _cache_path(congress, bill_type, number, "bill"),
            lambda: client.get_bill(congress, bill_type, number),
        )
        bill = bill_resp.get("bill", {})
        candidate.congress_gov_title = bill.get("title")
        candidate.policy_area = (bill.get("policySubject") or bill.get("policyArea") or {}).get("name") if isinstance(bill.get("policyArea"), dict) else (bill.get("policyArea") or {}).get("name") if bill.get("policyArea") else None

        sponsors = bill.get("sponsors") or []
        if sponsors:
            s0 = sponsors[0]
            name = s0.get("fullName") or s0.get("lastName")
            party = s0.get("party")
            state = s0.get("state")
            candidate.sponsor = f"{name} ({party}-{state})" if party and state else name

        candidate.introduced_date = bill.get("introducedDate")

        latest = bill.get("latestAction") or {}
        if latest:
            candidate.latest_action = f"{latest.get('actionDate', '')}: {latest.get('text', '')}".strip(": ")

        # Short title — look up titles endpoint? cheaper: pull from bill.titles if present
        titles = bill.get("titles", {})
        if isinstance(titles, dict) and "url" in titles:
            # nested endpoint, skip for speed unless needed
            pass

        # Subjects
        subjects = bill.get("subjects")
        if isinstance(subjects, dict) and "url" not in subjects:
            legi = subjects.get("legislativeSubjects") or []
            candidate.subjects = [s.get("name") for s in legi if s.get("name")]

        time.sleep(sleep_s)

        # Summaries (latest)
        try:
            summ_resp = _fetch_cached(
                _cache_path(congress, bill_type, number, "summaries"),
                lambda: client._get(f"/bill/{congress}/{bill_type}/{number}/summaries", format="json"),
            )
            summaries = summ_resp.get("summaries", [])
            if summaries:
                # Use the latest summary text (strip HTML tags crudely)
                latest_summary = max(summaries, key=lambda s: s.get("updateDate", ""))
                import re as _re
                candidate.summary_text = _re.sub(r"<[^>]+>", "", latest_summary.get("text", ""))
        except Exception as e:
            # Not all bills have summaries; ignore
            pass

        time.sleep(sleep_s)

    except Exception as e:
        candidate.reconciliation_error = f"{type(e).__name__}: {e}"
