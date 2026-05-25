"""P2 — Fetch a hand-curated seed of landmark federal redistricting and
voting-rights bills into data/corpus/redistricting/.

Why hand-curated and not the full govinfo-Solr sweep:
  - The full sweep (P4) requires real GovInfo + Congress.gov API keys to
    enumerate 100s of candidates and reconcile them. The seed is small
    enough to enumerate by hand from public knowledge.
  - The script falls back to unauthenticated www.govinfo.gov bulk-data
    URLs for the bill XML itself, so the only rate-limited step is the
    optional Congress.gov metadata enrichment.

Per-bill flow:
  1. Try fetching the bill XML at the unauthenticated bulk-data URL
     `https://www.govinfo.gov/content/pkg/BILLS-{congress}{type}{number}{ver}/xml/...`
     for version codes in priority order until one succeeds.
  2. Parse a minimum metadata block (title, sponsor, introduced_date,
     bill-stage) out of the XML — handles pre-USLM and USLM DTDs.
  3. Optionally enrich with Congress.gov (cosponsors, policy_area,
     subjects, latest_action). If the env lacks CONGRESS_GOV_API_KEY,
     fall back to DEMO_KEY at 10 req/hour — when that runs out, the
     bill is still written with thin metadata.
  4. Write data/corpus/redistricting/{bill_id}/{bill.xml, metadata.json,
     provenance.json}.

Run idempotently — existing bill dirs are skipped unless --force.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
import xml.etree.ElementTree as ET
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from ingest.promote import corpus_dir_for  # noqa: E402

# Version codes in priority order (most "final" first). The first one
# that returns XML wins.
VERSION_PRIORITY = [
    "pl", "enr", "eah", "eas", "es", "eh",
    "rh", "rs", "pcs", "pp", "ath", "ats",
    "ih", "is",
]

BULK_URL = "https://www.govinfo.gov/content/pkg/BILLS-{pkg}/xml/BILLS-{pkg}.xml"
CGOV_BASE = "https://api.congress.gov/v3"


# ---- Hand-curated seed list ----
# Notes:
#   - 117th Congress: post-Shelby-County and post-Rucho wave of voting-rights
#     and redistricting bills. HR 1 / S 1 (For the People Act) is the omnibus;
#     HR 4 / S 4 (John R. Lewis VRAA) restores preclearance; the Freedom to
#     Vote Act consolidates after For the People stalled in the Senate.
#   - 118th Congress: reintroductions plus Census-cycle-aware additions.
#   - Some bills may not have GovInfo packages (very new or never reported);
#     the script tolerates failures and reports them.
SEED_BILLS: list[tuple[int, str, int, str]] = [
    # IMPORTANT: bill numbers do NOT persist across Congresses for the
    # same bill name. "Prison Gerrymandering Act" had different HR
    # numbers in 117th vs. 118th. Verify each new entry against the
    # bill XML's <official-title> after fetching. The list below is
    # spot-checked to actually contain redistricting / voting-rights
    # content via sections_fts keyword density.
    #
    # 117th Congress (2021-2022)
    (117, "hr", 1,    "For the People Act of 2021"),
    (117, "hr", 4,    "John R. Lewis Voting Rights Advancement Act of 2021"),
    (117, "s",  1,    "For the People Act of 2021"),
    (117, "s",  4,    "John R. Lewis Voting Rights Advancement Act of 2021"),
    (117, "hr", 5746, "Freedom to Vote: John R. Lewis Act"),
    (117, "s",  2747, "Freedom to Vote Act"),
    (117, "hr", 3863, "Ranked Choice Voting Act (electoral reform — adjacent)"),
    # 118th Congress (2023-2024)
    (118, "hr", 11,   "Freedom to Vote Act"),
    (118, "hr", 14,   "John R. Lewis Voting Rights Advancement Act"),
    (118, "s",  1,    "For the People Act / Freedom to Vote Act"),
    (118, "s",  4,    "John R. Lewis Voting Rights Advancement Act"),
    # 119th Congress (2025-): only a few real entries; do NOT add
    # entries based on prior-Congress bill numbers without verifying.
    # 119-hr-1 is the FEHB Protection Act of 2025 (unrelated).
    (119, "hr", 14,   "John R. Lewis VRAA (119th)"),
]


@dataclass
class FetchResult:
    bill_id: str
    status: str           # 'added' | 'skipped-exists' | 'no-xml' | 'error'
    version_code: str | None = None
    package_id: str | None = None
    error: str | None = None
    enriched: bool = False


def _try_fetch_xml(congress: int, bill_type: str, number: int) -> tuple[bytes | None, str | None]:
    """Hit the unauthenticated bulk-data XML endpoint for each version
    code in priority order. Returns (xml_bytes, version_code) on the
    first success, or (None, None) when no version is available.

    Notes:
      - Many bills exist only at the 'ih' / 'is' stage. Iterating from
        most-final to most-initial means we return the most "canonical"
        text the government has published for the bill.
      - HTTP 404 = the GovInfo package for that version doesn't exist;
        any other error is re-raised so the caller can mark it.
    """
    for ver in VERSION_PRIORITY:
        pkg = f"{congress}{bill_type}{number}{ver}"
        url = BULK_URL.format(pkg=pkg)
        try:
            r = requests.get(url, timeout=30)
        except requests.RequestException as e:
            raise RuntimeError(f"network: {e}") from e
        if r.status_code == 404:
            continue
        # govinfo.gov serves a 200 HTML "page not found" for unknown
        # packages — must sniff the body. Real bill XML starts with
        # "<?xml" (after optional BOM). HTML error page starts with
        # "<!DOCTYPE html>".
        body = r.content.lstrip(b"\xef\xbb\xbf").lstrip()
        if not body.startswith(b"<?xml"):
            continue
        if b"<!DOCTYPE html" in body[:200]:
            continue
        return r.content, ver
    return None, None


def _parse_xml_metadata(xml_bytes: bytes) -> dict[str, Any]:
    """Best-effort metadata pull from bill XML. Handles pre-USLM (the
    `<bill>` DTD used by most pre-2017 bills) and USLM.

    Returns a dict with whatever could be extracted; missing fields are
    omitted. The downstream metadata.json schema is forgiving.
    """
    out: dict[str, Any] = {}
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return out

    # USLM has namespaces; pre-USLM is naked. Helper that ignores ns:
    def _lname(elem) -> str:
        t = elem.tag
        return t.rsplit("}", 1)[-1] if isinstance(t, str) and "}" in t else t

    # Walk for the most-canonical title and sponsor.
    for el in root.iter():
        ln = _lname(el)
        if ln == "official-title" and "title" not in out:
            txt = " ".join((el.text or "").split())
            if txt:
                out["title"] = txt
        elif ln == "short-title" and "short_title" not in out:
            txt = " ".join((el.text or "").split())
            if txt:
                out["short_title"] = txt
        elif ln == "sponsor" and "sponsor" not in out:
            # name-search element is common in pre-USLM
            ns = el.find(".//name-search")
            if ns is not None and ns.text:
                out["sponsor"] = ns.text.strip()
            else:
                txt = " ".join("".join(el.itertext()).split())
                if txt:
                    out["sponsor"] = txt[:200]
        elif ln == "action-date" and "introduced_date" not in out:
            d = el.get("date") or (el.text or "").strip()
            if d and len(d) >= 8:
                out["introduced_date"] = d[:10] if "-" in d else f"{d[:4]}-{d[4:6]}-{d[6:8]}"

    # Bill stage from the root attribute
    stage = root.get("bill-stage")
    if stage:
        out["bill_stage"] = stage

    return out


def _enrich_from_congress_gov(
    congress: int, bill_type: str, number: int, api_key: str,
) -> dict[str, Any]:
    """Optional Congress.gov enrichment. Returns whatever the API gives
    us; failures (rate-limit, 404) return an empty dict.
    """
    out: dict[str, Any] = {}
    try:
        r = requests.get(
            f"{CGOV_BASE}/bill/{congress}/{bill_type}/{number}",
            params={"format": "json"},
            headers={"X-API-Key": api_key, "Accept": "application/json"},
            timeout=15,
        )
        if r.status_code != 200:
            return out
        bill = r.json().get("bill", {})
        out["congress_gov_title"] = bill.get("title")
        out["policy_area"] = (bill.get("policyArea") or {}).get("name")
        sponsors = bill.get("sponsors", [])
        if sponsors:
            out["sponsor"] = sponsors[0].get("fullName")
        la = bill.get("latestAction", {})
        if la.get("actionDate") and la.get("text"):
            out["latest_action"] = f"{la['actionDate']}: {la['text']}"
        if bill.get("introducedDate"):
            out["introduced_date"] = bill["introducedDate"]
        # Subjects is a separate endpoint; skip for the seed (DEMO budget).
    except requests.RequestException:
        pass
    return out


def _fetch_one(
    congress: int, bill_type: str, number: int,
    *,
    cgov_api_key: str,
    cgov_budget: list[int],   # mutable counter; element 0 = remaining calls
    force: bool = False,
) -> FetchResult:
    bill_id = f"{congress}-{bill_type}-{number}"
    target = corpus_dir_for("redistricting") / bill_id
    if target.exists() and not force:
        return FetchResult(bill_id=bill_id, status="skipped-exists")

    xml_bytes, version_code = _try_fetch_xml(congress, bill_type, number)
    if xml_bytes is None:
        return FetchResult(bill_id=bill_id, status="no-xml")

    target.mkdir(parents=True, exist_ok=True)
    (target / "bill.xml").write_bytes(xml_bytes)

    xml_meta = _parse_xml_metadata(xml_bytes)

    enriched = False
    cgov_meta: dict[str, Any] = {}
    if cgov_budget[0] > 0:
        cgov_meta = _enrich_from_congress_gov(congress, bill_type, number, cgov_api_key)
        cgov_budget[0] -= 1
        if cgov_meta:
            enriched = True

    pkg = f"{congress}{bill_type}{number}{version_code}"
    canonical = {
        "package_id": f"BILLS-{pkg}",
        "version_code": version_code,
        "date_issued": xml_meta.get("introduced_date") or cgov_meta.get("introduced_date") or "",
    }

    # Compose metadata.json — pull title from cgov when richer, else XML.
    title = cgov_meta.get("congress_gov_title") or xml_meta.get("title")
    sponsor = cgov_meta.get("sponsor") or xml_meta.get("sponsor")
    metadata = {
        "bill_id": bill_id,
        "congress": congress,
        "bill_type": bill_type,
        "bill_number": number,
        "title": title,
        "short_title": xml_meta.get("short_title"),
        "sponsor": sponsor,
        "introduced_date": cgov_meta.get("introduced_date") or xml_meta.get("introduced_date"),
        "latest_action": cgov_meta.get("latest_action"),
        "policy_area": cgov_meta.get("policy_area"),
        "subjects": [],
        "summary_text": None,
        "centrality_score": None,
        "match_locations": {},
        "tier": "A",  # all seed bills are landmark — tier A by curation
        "stream": "legislation",
        "topic": "redistricting",
        "versions_available": [canonical],
        "canonical_version": canonical,
        "actions": [],
        "cosponsors": [],
        # Metadata-source notes — agent should know what's been enriched
        # and what was bulk-data-only, so it can hedge appropriately.
        "_metadata_sources": {
            "xml": "govinfo bulk-data (unauthenticated)",
            "congress_gov_enriched": enriched,
        },
    }
    (target / "metadata.json").write_text(
        json.dumps(metadata, indent=2, default=str) + "\n"
    )
    provenance = {
        "bill_id": bill_id,
        "criteria_version": "redistricting-seed-v1.0",
        "canonical_package_id": canonical["package_id"],
        "sources": {
            "bill_xml": BULK_URL.format(pkg=pkg),
            "congress_gov_enrichment": (
                f"{CGOV_BASE}/bill/{congress}/{bill_type}/{number}"
                if enriched else None
            ),
        },
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    (target / "provenance.json").write_text(json.dumps(provenance, indent=2))

    return FetchResult(
        bill_id=bill_id, status="added", version_code=version_code,
        package_id=canonical["package_id"], enriched=enriched,
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="re-fetch even if dir exists")
    ap.add_argument("--limit", type=int, default=None, help="cap number of bills attempted")
    ap.add_argument("--sleep", type=float, default=0.25, help="seconds between bills")
    args = ap.parse_args()

    cgov_key = os.environ.get("CONGRESS_GOV_API_KEY") or "DEMO_KEY"
    using_demo = cgov_key == "DEMO_KEY" or not os.environ.get("CONGRESS_GOV_API_KEY")
    if using_demo:
        print("[warn] CONGRESS_GOV_API_KEY missing — using DEMO_KEY (10 req/hour). "
              "Bills will be ingested with thin metadata after the budget runs out.")
    # DEMO_KEY budget — leave some headroom for retries
    cgov_budget = [10 if using_demo else 1000]

    bills = SEED_BILLS[: args.limit] if args.limit else SEED_BILLS
    print(f"[seed] attempting {len(bills)} bills")

    stats = {"added": 0, "skipped-exists": 0, "no-xml": 0, "error": 0}
    enriched_count = 0
    results: list[FetchResult] = []
    for i, (congress, bill_type, number, label) in enumerate(bills, 1):
        try:
            res = _fetch_one(
                congress, bill_type, number,
                cgov_api_key=cgov_key, cgov_budget=cgov_budget, force=args.force,
            )
        except Exception as e:
            res = FetchResult(
                bill_id=f"{congress}-{bill_type}-{number}",
                status="error", error=f"{type(e).__name__}: {e}",
            )
        results.append(res)
        stats[res.status] = stats.get(res.status, 0) + 1
        if res.enriched:
            enriched_count += 1
        marker = {
            "added": "+", "skipped-exists": "=", "no-xml": "-", "error": "!",
        }[res.status]
        enrich_mark = " (enriched)" if res.enriched else ""
        ver = f" [{res.version_code}]" if res.version_code else ""
        print(f"  {marker} {i:>2}/{len(bills)}  {res.bill_id:<14}{ver}  {label[:60]}{enrich_mark}")
        if res.error:
            print(f"     error: {res.error}")
        if i < len(bills):
            time.sleep(args.sleep)

    print(f"\n[done] {stats}  cgov_remaining={cgov_budget[0]}  enriched={enriched_count}")
    return 0 if stats["error"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
