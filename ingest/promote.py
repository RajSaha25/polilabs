"""Phase 1.3 — promote candidates to the structured corpus.

For each included candidate:
  - Pick canonical version (enrolled > engrossed > introduced ranking)
  - Fetch USLM XML and HTM from GovInfo
  - Fetch additional Congress.gov metadata (actions, cosponsors)
  - Write data/corpus/legislation/{bill_id}/
        bill.xml          USLM XML of canonical version
        bill.htm          HTM (HTML rendering) of canonical version
        metadata.json     consolidated bill metadata
        provenance.json   source URLs, package id, fetch timestamps, criteria version

Idempotent: if a bill_id directory already exists, the bill is skipped unless
`force` is set.
"""
from __future__ import annotations

import csv
import json
import os
import re
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import requests

from sources.congress_gov import CongressGov

from .candidate import Candidate, PackageRef

CORPUS_DIR = Path("data/corpus/legislation")
CACHE_DIR = Path("data/cache/govinfo")
DEFAULT_HEURISTIC_THRESHOLD = 3.0
CRITERIA_VERSION = "v1.0"


def _govinfo_get(url: str, *, api_key: str, timeout: float = 60.0) -> bytes:
    """Authenticated GovInfo content fetch. Returns raw bytes."""
    sep = "&" if "?" in url else "?"
    r = requests.get(f"{url}{sep}api_key={api_key}", timeout=timeout)
    r.raise_for_status()
    return r.content


def _cache_get(package_id: str, fmt: str, *, api_key: str) -> bytes | None:
    """Fetch GovInfo package content with on-disk caching.

    Returns None when GovInfo does not serve the requested format for this
    package. GovInfo signals this with HTTP 400 (with a JSON error body) or
    404 depending on the format; both are treated as "not available."
    """
    cache_path = CACHE_DIR / f"{package_id}.{fmt}"
    if cache_path.exists():
        return cache_path.read_bytes()
    url = f"https://api.govinfo.gov/packages/{package_id}/{fmt}"
    try:
        data = _govinfo_get(url, api_key=api_key)
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code in (400, 404):
            return None
        raise
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_bytes(data)
    return data


# ---- inclusion logic ----

def load_review_csv(path: Path) -> dict[str, dict]:
    """Return {bill_id: {include, tier, notes}} from review.csv. Empty if unreviewed."""
    if not path.exists():
        return {}
    out: dict[str, dict] = {}
    with open(path) as f:
        for row in csv.DictReader(f):
            inc = (row.get("include (y/n)") or "").strip().lower()
            tier = (row.get("tier (A/B)") or "").strip().upper()
            notes = (row.get("notes") or "").strip()
            if inc or tier or notes:  # only record rows with any human input
                out[row["bill_id"]] = {"include": inc, "tier": tier, "notes": notes}
    return out


def decide_inclusion(
    c: Candidate,
    review_row: dict | None,
    *,
    threshold: float,
) -> tuple[bool, str | None, str]:
    """Return (include?, tier, decision_source)."""
    if review_row:
        inc = review_row.get("include", "")
        if inc == "y":
            return True, review_row.get("tier") or c.proposed_tier, "human-review"
        if inc == "n":
            return False, None, "human-review"
        # row present but include blank → fall through to heuristic
    include = c.centrality_score >= threshold
    return include, (c.proposed_tier if include else None), "heuristic"


# ---- promotion ----

def _pick_canonical(versions: list[PackageRef]) -> PackageRef | None:
    """Versions list is already sorted by priority desc, date asc. Pick first."""
    return versions[0] if versions else None


def _load_cached_congress_gov(bill_id: str) -> tuple[dict | None, dict | None]:
    """Read the Congress.gov bill + summaries JSON cached during Phase 1.1."""
    cache = Path("data/cache/congress_gov")
    bill_p = cache / f"{bill_id}.bill.json"
    summ_p = cache / f"{bill_id}.summaries.json"
    bill = json.loads(bill_p.read_text()) if bill_p.exists() else None
    summ = json.loads(summ_p.read_text()) if summ_p.exists() else None
    return bill, summ


def _fetch_supplemental_metadata(
    cgov: CongressGov, candidate: Candidate
) -> dict:
    """Fetch actions + cosponsors with on-disk cache."""
    cache = Path("data/cache/congress_gov")
    cache.mkdir(parents=True, exist_ok=True)
    bill_id = candidate.bill_id
    c, t, n = candidate.congress, candidate.bill_type, candidate.bill_number

    out: dict[str, list] = {"actions": [], "cosponsors": []}

    actions_p = cache / f"{bill_id}.actions.json"
    if actions_p.exists():
        out["actions"] = json.loads(actions_p.read_text()).get("actions", [])
    else:
        try:
            resp = cgov.get_bill_actions(c, t, n)
            actions_p.write_text(json.dumps(resp, indent=2))
            out["actions"] = resp.get("actions", [])
        except Exception as e:
            out["actions_error"] = f"{type(e).__name__}: {e}"

    cospo_p = cache / f"{bill_id}.cosponsors.json"
    if cospo_p.exists():
        out["cosponsors"] = json.loads(cospo_p.read_text()).get("cosponsors", [])
    else:
        try:
            resp = cgov._get(f"/bill/{c}/{t}/{n}/cosponsors", format="json")
            cospo_p.write_text(json.dumps(resp, indent=2))
            out["cosponsors"] = resp.get("cosponsors", [])
        except Exception as e:
            out["cosponsors_error"] = f"{type(e).__name__}: {e}"

    return out


def promote_one(
    candidate: Candidate,
    *,
    cgov: CongressGov,
    govinfo_api_key: str,
    force: bool = False,
) -> dict:
    """Promote a single candidate. Returns a status dict for logging."""
    bill_id = candidate.bill_id
    target = CORPUS_DIR / bill_id

    if target.exists() and not force:
        return {"bill_id": bill_id, "status": "skipped-exists"}

    canonical = _pick_canonical(candidate.versions)
    if canonical is None:
        return {"bill_id": bill_id, "status": "error", "error": "no-versions"}

    target.mkdir(parents=True, exist_ok=True)

    # GovInfo XML/USLM and HTM
    xml_bytes = _cache_get(canonical.package_id, "uslm", api_key=govinfo_api_key)
    if xml_bytes is None:
        xml_bytes = _cache_get(canonical.package_id, "xml", api_key=govinfo_api_key)
    htm_bytes = _cache_get(canonical.package_id, "htm", api_key=govinfo_api_key)

    if xml_bytes:
        (target / "bill.xml").write_bytes(xml_bytes)
    if htm_bytes:
        (target / "bill.htm").write_bytes(htm_bytes)

    # Consolidated metadata
    cgov_bill, cgov_summ = _load_cached_congress_gov(bill_id)
    supplemental = _fetch_supplemental_metadata(cgov, candidate)

    metadata = {
        "bill_id": bill_id,
        "congress": candidate.congress,
        "bill_type": candidate.bill_type,
        "bill_number": candidate.bill_number,
        "title": candidate.congress_gov_title,
        "short_title": candidate.short_title,
        "sponsor": candidate.sponsor,
        "introduced_date": candidate.introduced_date,
        "latest_action": candidate.latest_action,
        "policy_area": candidate.policy_area,
        "subjects": candidate.subjects,
        "summary_text": candidate.summary_text,
        "centrality_score": candidate.centrality_score,
        "match_locations": candidate.match_locations,
        "tier": candidate.proposed_tier,
        "stream": "legislation",
        # `topic` = policy-domain corpus tag. P1 ingest emits the v1
        # corpus default; the P2 redistricting pipeline overrides via a
        # candidate-level topic field added in that PR.
        "topic": getattr(candidate, "topic", None) or "ai_governance",
        "versions_available": [
            {"package_id": v.package_id, "version_code": v.version_code, "date_issued": v.date_issued}
            for v in candidate.versions
        ],
        "canonical_version": {
            "package_id": canonical.package_id,
            "version_code": canonical.version_code,
            "date_issued": canonical.date_issued,
        },
        "actions": supplemental.get("actions", []),
        "cosponsors": supplemental.get("cosponsors", []),
    }
    (target / "metadata.json").write_text(json.dumps(metadata, indent=2, default=str))

    # Provenance
    provenance = {
        "bill_id": bill_id,
        "criteria_version": CRITERIA_VERSION,
        "canonical_package_id": canonical.package_id,
        "sources": {
            "govinfo_xml": f"https://api.govinfo.gov/packages/{canonical.package_id}/uslm",
            "govinfo_htm": f"https://api.govinfo.gov/packages/{canonical.package_id}/htm",
            "congress_gov_bill": f"https://api.congress.gov/v3/bill/{candidate.congress}/{candidate.bill_type}/{candidate.bill_number}",
        },
        "files": {
            "bill.xml": bool(xml_bytes),
            "bill.htm": bool(htm_bytes),
            "metadata.json": True,
        },
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    (target / "provenance.json").write_text(json.dumps(provenance, indent=2))

    return {
        "bill_id": bill_id,
        "status": "added",
        "xml": bool(xml_bytes),
        "htm": bool(htm_bytes),
        "package_id": canonical.package_id,
    }


def write_corpus_index(promoted: list[dict]) -> None:
    """Write a top-level index of the corpus for quick discovery."""
    CORPUS_DIR.parent.mkdir(parents=True, exist_ok=True)
    index = {
        "corpus_version": "v1.0",
        "criteria_version": CRITERIA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stream": "legislation",
        "bill_count": sum(1 for p in promoted if p["status"] in ("added", "skipped-exists")),
        "bills": sorted([p["bill_id"] for p in promoted if p["status"] in ("added", "skipped-exists")]),
    }
    (CORPUS_DIR.parent / "INDEX.json").write_text(json.dumps(index, indent=2))
