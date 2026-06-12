"""Fetch the hand-curated `secret_congress` seed corpus into
data/corpus/secret_congress/.

See corpus/secret_congress_criteria.md for what this corpus is and the
cluster vocabulary. Every entry below was verified against its BILLSTATUS
record (title + public-law number) on 2026-06-09 before being added —
bill numbers are never trusted from memory.

Differences from scripts/fetch_redistricting_seed.py (the template):
  - Metadata enrichment comes from the keyless GovInfo BILLSTATUS bulk
    feed (`ingest/billstatus.py`) instead of the rate-limited
    Congress.gov DEMO_KEY path. BILLSTATUS carries structured sponsor,
    cosponsors, actions, policy area, and subjects, so every seed bill
    gets full metadata without any API key.
  - Each bill also gets `billstatus.json` next to metadata.json:
    roll-call votes with per-party splits, a derived outcome
    (enacted / failed_cloture / ...), and the event trail behind it.
  - Each bill carries a `cluster` tag and a short `curator_note`.

Run idempotently — existing bill dirs are skipped unless --force.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ingest.promote import corpus_dir_for  # noqa: E402
from ingest.billstatus import (  # noqa: E402
    BILLSTATUS_URL,
    enrich_bill_dir,
    fetch_billstatus_xml,
    parse_billstatus,
)
# Reuse the template's pure helpers rather than duplicating them.
from fetch_redistricting_seed import (  # noqa: E402
    BULK_URL,
    _parse_xml_metadata,
    _try_fetch_xml,
)

TOPIC = "secret_congress"
CRITERIA_VERSION = "secret-congress-seed-v1.0"

# (congress, type, number, cluster, label, curator_note)
# Clusters defined in corpus/secret_congress_criteria.md.
SEED_BILLS: list[tuple[int, str, int, str, str, str]] = [
    # ---- Quiet bipartisan laws: the secret-congress core case ----
    (117, "s", 3580, "quiet_bipartisan_law", "Ocean Shipping Reform Act of 2022",
     "Enacted PL 117-146. Passed the Senate by unanimous consent and the House "
     "369-42 with minimal national coverage — a canonical secret-congress case."),
    (117, "hr", 3076, "quiet_bipartisan_law", "Postal Service Reform Act of 2022",
     "Enacted PL 117-108. Decades-stalled USPS finance overhaul passed "
     "342-92 in the House and 79-19 in the Senate with little media attention."),
    (117, "s", 3373, "quiet_bipartisan_law", "Honoring our PACT Act (Heath Robinson)",
     "Enacted PL 117-168. Largest veterans-benefits expansion in decades; final "
     "Senate vote 86-11 after a brief, loud procedural blockade — the exception "
     "that tests the salience rule."),
    (118, "s", 4367, "quiet_bipartisan_law", "Thomas R. Carper WRDA of 2024",
     "Enacted PL 118-272. The notes' 'water infrastructure' exemplar: biennial "
     "water-projects authorization that passes near-unanimously every cycle "
     "while attracting almost no national coverage."),
    (117, "s", 914, "quiet_bipartisan_law", "Drinking Water and Wastewater Infrastructure Act of 2021",
     "Passed the Senate 89-2, then its substance was carried into the IIJA. "
     "Both a quiet-bipartisan exemplar and an absorbed-into-vehicle case; "
     "clustered here because the Senate vote is the salient datum."),
    (119, "s", 331, "quiet_bipartisan_law", "HALT Fentanyl Act",
     "Enacted PL 119-26. Permanent fentanyl-analogue scheduling passed "
     "84-16 / 321-104 in a polarized Congress with modest coverage."),
    (119, "s", 146, "quiet_bipartisan_law", "TAKE IT DOWN Act",
     "Enacted PL 119-12. Criminalizes non-consensual intimate imagery incl. "
     "AI deepfakes; near-unanimous in both chambers."),
    (118, "hr", 3935, "quiet_bipartisan_law", "FAA Reauthorization Act of 2024",
     "Enacted PL 118-63. Must-pass aviation authorization, 387-26 in the House: "
     "the routine, invisible bipartisan workhorse class."),

    # ---- High-salience bipartisan laws ----
    (117, "hr", 4346, "high_salience_bipartisan_law", "CHIPS and Science Act",
     "Enacted PL 117-167. The notes' headline exemplar. Final votes: Senate "
     "64-33, House 243-187. The bill spent a year as a shell (House-passed "
     "America COMPETES, 222-210 near-party-line) before the bipartisan deal."),
    (117, "hr", 3684, "high_salience_bipartisan_law", "Infrastructure Investment and Jobs Act",
     "Enacted PL 117-58. Senate 69-30; House 228-206 with 13 R yeas after "
     "months of coupling to the partisan reconciliation bill — salience "
     "nearly killed a bipartisan deal."),
    (117, "s", 2938, "high_salience_bipartisan_law", "Bipartisan Safer Communities Act",
     "Enacted PL 117-159. First significant gun legislation in ~30 years, "
     "Senate 65-33 weeks after Uvalde — high salience, bipartisan anyway."),
    (117, "hr", 8404, "high_salience_bipartisan_law", "Respect for Marriage Act",
     "Enacted PL 117-228. Codified marriage recognition with 12 R Senate "
     "yeas (61-36) in a lame duck."),
    (118, "hr", 3746, "high_salience_bipartisan_law", "Fiscal Responsibility Act of 2023",
     "Enacted PL 118-5. Debt-ceiling deal, House 314-117: both parties "
     "supplied majorities under default deadline pressure."),
    (118, "hr", 82, "high_salience_bipartisan_law", "Social Security Fairness Act",
     "Enacted PL 118-273. WEP/GPO repeal forced to the floor by discharge "
     "petition, House 327-75, Senate 76-20 — bipartisan majority overriding "
     "leadership scheduling."),
    (119, "s", 5, "high_salience_bipartisan_law", "Laken Riley Act",
     "Enacted PL 119-1. Immigration detention mandate; 12 Senate and 46 House "
     "Democrats joined all Republicans — post-2024-election crossover under "
     "electoral pressure."),

    # ---- Bipartisan support on the record, but died ----
    (118, "s", 4361, "bipartisan_but_died", "Border Act of 2024",
     "Failed cloture 43-50 (2024-05-23) after months of bipartisan "
     "negotiation; support collapsed when the presidential campaign made "
     "the border a mobilizing issue. The notes' 'electoral pressure kills "
     "bills' case."),
    (118, "hr", 7024, "bipartisan_but_died", "Tax Relief for American Families and Workers Act",
     "Passed the House 357-70, then failed Senate cloture 48-44 "
     "(2024-08-01) as Republicans anticipated better terms after the "
     "election — bipartisan in one chamber, electoral-calendar casualty in "
     "the other."),
    (118, "s", 1409, "bipartisan_but_died", "Kids Online Safety Act",
     "Reported from Commerce; its text passed the Senate 91-3 (2024-07-30) "
     "inside the Kids Online Safety and Privacy Act vehicle (S.2073), so "
     "S.1409 itself shows no floor vote. The House never took it up. "
     "Near-unanimity in one chamber is not passage."),
    (117, "s", 2992, "bipartisan_but_died", "American Innovation and Choice Online Act",
     "Reported from Judiciary 16-6 with bipartisan cosponsors; never "
     "received a floor vote amid intense platform lobbying — a "
     "donor/lobbying failure mode with no roll-call evidence by design."),
    (117, "s", 673, "bipartisan_but_died", "Journalism Competition and Preservation Act",
     "Bipartisan cosponsorship, committee action, no floor vote — died "
     "quietly under platform opposition."),
    (117, "hr", 1996, "bipartisan_but_died", "SAFE Banking Act of 2021",
     "Passed the House 321-101 with 106 R yeas; never voted in the Senate. "
     "Repeated chamber-asymmetry case (passed the House in multiple "
     "Congresses)."),
    (117, "s", 4822, "bipartisan_but_died", "DISCLOSE Act of 2022",
     "Failed cloture 49-49 on party lines. The corpus's direct "
     "donor-transparency case: a campaign-finance disclosure bill blocked "
     "by the party benefiting from undisclosed spending."),

    # ---- Absorbed into a vehicle ----
    (117, "s", 1260, "absorbed_into_vehicle", "USICA / Endless Frontier Act",
     "The notes' 'FRONTIERS Act'. Passed the Senate 68-32 as USICA; died in "
     "conference and its science-policy core was enacted inside the CHIPS "
     "and Science Act."),
    (117, "s", 4573, "absorbed_into_vehicle", "Electoral Count Reform Act of 2022",
     "Reported 14-1 from Rules; never voted standalone. Enacted inside the "
     "FY2023 omnibus (117-hr-2617) — the single-bill bundling pattern from "
     "the notes."),

    # ---- Omnibus vehicles ----
    (117, "hr", 2617, "omnibus_vehicle", "Consolidated Appropriations Act, 2023",
     "PL 117-328. One vote carried ECRA, SECURE 2.0, the Pregnant Workers "
     "Fairness Act, and full-year appropriations — bundling as the price "
     "of floor time."),
    (117, "hr", 7776, "omnibus_vehicle", "WRDA 2022 -> NDAA FY2023 vehicle",
     "PL 117-263. Introduced as the Water Resources Development Act of "
     "2022, became the James M. Inhofe NDAA and carried WRDA to enactment "
     "— the water-infrastructure exemplar travelling inside a must-pass "
     "vehicle."),

    # ---- Party-line contrast class ----
    (117, "hr", 5376, "party_line_contrast", "Inflation Reduction Act of 2022",
     "Enacted PL 117-169 via reconciliation, 51-50 / 220-207 with zero "
     "minority-party votes — the procedural opposite of the secret-congress "
     "path."),
    (119, "hr", 1, "party_line_contrast", "One Big Beautiful Bill Act",
     "Enacted PL 119-21 via reconciliation on party-line votes — the 119th "
     "Congress contrast case."),
    (118, "hr", 2, "party_line_contrast", "Secure the Border Act of 2023",
     "Passed the House 219-213 with zero D yeas; never taken up in the "
     "Senate. A messaging bill: contrast case for the Border Act's failed "
     "bipartisan deal."),
]


def _fetch_one(entry: tuple[int, str, int, str, str, str], *, force: bool) -> str:
    congress, bill_type, number, cluster, label, note = entry
    bill_id = f"{congress}-{bill_type}-{number}"
    target = corpus_dir_for(TOPIC) / bill_id
    if target.exists() and not force:
        return "skipped-exists"

    xml_bytes, version_code = _try_fetch_xml(congress, bill_type, number)
    if xml_bytes is None:
        return "no-xml"

    raw_status = fetch_billstatus_xml(congress, bill_type, number)
    status = parse_billstatus(raw_status) if raw_status else None

    target.mkdir(parents=True, exist_ok=True)
    (target / "bill.xml").write_bytes(xml_bytes)

    xml_meta = _parse_xml_metadata(xml_bytes)
    pkg = f"{congress}{bill_type}{number}{version_code}"
    canonical = {
        "package_id": f"BILLS-{pkg}",
        "version_code": version_code,
        "date_issued": (status or {}).get("introduced_date")
                       or xml_meta.get("introduced_date") or "",
    }

    sponsor = None
    if status and status.get("sponsor"):
        sponsor = status["sponsor"].get("fullName")
    sponsor = sponsor or xml_meta.get("sponsor")

    latest_action = None
    if status and status["latest_action"]["text"]:
        la = status["latest_action"]
        latest_action = f"{la['actionDate']}: {la['text']}"

    metadata = {
        "bill_id": bill_id,
        "congress": congress,
        "bill_type": bill_type,
        "bill_number": number,
        "title": (status or {}).get("title") or xml_meta.get("title"),
        "short_title": xml_meta.get("short_title"),
        "sponsor": sponsor,
        "introduced_date": (status or {}).get("introduced_date") or xml_meta.get("introduced_date"),
        "latest_action": latest_action,
        "policy_area": (status or {}).get("policy_area"),
        "subjects": (status or {}).get("subjects") or [],
        "summary_text": None,
        "centrality_score": None,
        "match_locations": {},
        "tier": "A",
        "stream": "legislation",
        "topic": TOPIC,
        "cluster": cluster,
        "curator_note": note,
        "versions_available": [canonical],
        "canonical_version": canonical,
        "actions": (status or {}).get("actions") or [],
        "cosponsors": (status or {}).get("cosponsors") or [],
        "_metadata_sources": {
            "xml": "govinfo bulk-data (unauthenticated)",
            "billstatus": "govinfo BILLSTATUS bulk-data (unauthenticated)",
            "congress_gov_enriched": False,
        },
    }
    (target / "metadata.json").write_text(json.dumps(metadata, indent=2, default=str) + "\n")

    provenance = {
        "bill_id": bill_id,
        "criteria_version": CRITERIA_VERSION,
        "canonical_package_id": canonical["package_id"],
        "cluster": cluster,
        "sources": {
            "bill_xml": BULK_URL.format(pkg=pkg),
            "billstatus": BILLSTATUS_URL.format(
                congress=congress, bill_type=bill_type, number=number),
        },
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    (target / "provenance.json").write_text(json.dumps(provenance, indent=2))

    # Votes + outcome + event trail -> billstatus.json
    enrich_status = enrich_bill_dir(target, force=force)
    return f"added({version_code},{enrich_status})"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="re-fetch even if dir exists")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--sleep", type=float, default=0.5)
    args = ap.parse_args()

    bills = SEED_BILLS[: args.limit] if args.limit else SEED_BILLS
    print(f"[seed] attempting {len(bills)} bills -> data/corpus/{TOPIC}/")
    failures = 0
    for i, entry in enumerate(bills, 1):
        congress, bill_type, number, cluster, label, _ = entry
        try:
            res = _fetch_one(entry, force=args.force)
        except Exception as e:
            res = f"error: {type(e).__name__}: {e}"
        if res.startswith(("no-", "error")):
            failures += 1
        print(f"  {i:>2}/{len(bills)}  {congress}-{bill_type}-{number:<5} {res:<28} [{cluster}] {label[:50]}")
        if i < len(bills):
            time.sleep(args.sleep)
    print(f"[done] failures={failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
