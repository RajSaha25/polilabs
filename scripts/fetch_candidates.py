"""Phase 1.1 — Fetch AI-governance candidate bills.

Pipeline:
  1. GovInfo full-text search for the inclusion-criteria keyword set
     across BILLS collection, 118th + 119th Congress.
  2. Deduplicate hits to unique bills by (congress, type, number).
  3. Reconcile each unique bill against Congress.gov for metadata
     (title, sponsor, summary, subjects, latest action).
  4. Apply the centrality scorer (anchor gate + weighted location matching).
  5. Sort by centrality and emit:
       - data/candidates/candidates_v1.jsonl (full records)
       - data/candidates/review.csv (human spot-check sheet)

Outputs are written incrementally; the script is safely re-runnable.
"""
from __future__ import annotations

import csv
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from ingest import govinfo_search
from ingest.candidate import (
    IN_SCOPE_TYPES,
    Candidate,
    PackageRef,
    parse_package_id,
    score_centrality,
)
from ingest.reconcile import reconcile_bill
from sources.congress_gov import CongressGov

DATA_DIR = Path("data/candidates")
START_DATE = "2023-01-03"
END_DATE = "2026-12-31"

# Versions ranked by canonicality — highest wins as the "representative" package
_VERSION_PRIORITY = {
    "pl": 99, "enr": 90, "eas": 80, "eah": 80, "es": 70, "eh": 70,
    "rs": 60, "rh": 60, "is": 50, "ih": 50, "ats": 40, "ath": 40,
}


def _version_rank(version: str) -> int:
    return _VERSION_PRIORITY.get(version, 0)


def collect_govinfo_hits() -> list[dict]:
    """Run the GovInfo search and return all raw hits."""
    query = govinfo_search.build_query(START_DATE, END_DATE)
    print(f"[govinfo] query: {query[:200]}...")
    hits = []
    last_log = time.time()
    for i, hit in enumerate(govinfo_search.search(query)):
        hits.append(hit)
        if time.time() - last_log > 3:
            print(f"[govinfo]   fetched {len(hits)} hits...")
            last_log = time.time()
    print(f"[govinfo] total hits: {len(hits)}")
    return hits


def dedupe_to_candidates(hits: list[dict]) -> list[Candidate]:
    """Group hits by (congress, type, number) into Candidate objects."""
    groups: dict[tuple[int, str, int], list[PackageRef]] = defaultdict(list)
    skipped_out_of_scope_types = 0
    skipped_unparseable = 0

    for hit in hits:
        pkg = hit.get("packageId", "")
        parsed = parse_package_id(pkg)
        if parsed is None:
            skipped_unparseable += 1
            continue
        congress, bill_type, number, version = parsed
        if bill_type not in IN_SCOPE_TYPES:
            skipped_out_of_scope_types += 1
            continue
        ref = PackageRef(
            package_id=pkg,
            version_code=version,
            date_issued=hit.get("dateIssued", ""),
            title=hit.get("title", ""),
        )
        groups[(congress, bill_type, number)].append(ref)

    candidates: list[Candidate] = []
    for (congress, bill_type, number), refs in groups.items():
        refs_sorted = sorted(refs, key=lambda r: (-_version_rank(r.version_code), r.date_issued), reverse=False)
        candidates.append(
            Candidate(
                bill_id=f"{congress}-{bill_type}-{number}",
                congress=congress,
                bill_type=bill_type,
                bill_number=number,
                versions=refs_sorted,
                govinfo_titles=[r.title for r in refs_sorted],
            )
        )

    print(f"[dedupe] unique bills: {len(candidates)}")
    print(f"[dedupe] skipped out-of-scope types (hres/sres): {skipped_out_of_scope_types}")
    print(f"[dedupe] skipped unparseable package ids: {skipped_unparseable}")
    return candidates


def reconcile_all(candidates: list[Candidate]) -> None:
    client = CongressGov()
    n = len(candidates)
    errors = 0
    print(f"[reconcile] fetching Congress.gov metadata for {n} bills (cached on disk)")
    last_log = time.time()
    for i, c in enumerate(candidates):
        reconcile_bill(client, c)
        if c.reconciliation_error:
            errors += 1
        if time.time() - last_log > 3:
            print(f"[reconcile]   {i + 1}/{n}  errors={errors}")
            last_log = time.time()
    print(f"[reconcile] done. errors={errors}/{n}")


def score_all(candidates: list[Candidate]) -> None:
    for c in candidates:
        score_centrality(c)


def write_outputs(candidates: list[Candidate]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Filter by anchor gate (inclusion criteria)
    in_scope = [c for c in candidates if c.has_anchor]
    out_scope = [c for c in candidates if not c.has_anchor]
    print(f"[filter] anchor-gate kept {len(in_scope)} of {len(candidates)}; "
          f"{len(out_scope)} excluded (no anchor keyword in metadata)")

    # Sort by score descending
    in_scope.sort(key=lambda c: c.centrality_score, reverse=True)

    # JSONL — full records
    jsonl_path = DATA_DIR / "candidates_v1.jsonl"
    with open(jsonl_path, "w") as f:
        for c in in_scope:
            f.write(json.dumps(c.to_dict(), default=str) + "\n")
    print(f"[write] {jsonl_path}  ({len(in_scope)} rows)")

    # Review CSV — spot-check sheet
    csv_path = DATA_DIR / "review.csv"
    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "bill_id", "centrality_score", "proposed_tier",
            "title", "sponsor", "introduced_date", "policy_area",
            "match_locations", "summary_first_200",
            "include (y/n)", "tier (A/B)", "notes",
        ])
        for c in in_scope:
            w.writerow([
                c.bill_id,
                c.centrality_score,
                c.proposed_tier or "",
                (c.congress_gov_title or c.govinfo_titles[0] if c.govinfo_titles else "")[:200],
                c.sponsor or "",
                c.introduced_date or "",
                c.policy_area or "",
                ";".join(f"{loc}:{','.join(terms)}" for loc, terms in c.match_locations.items()),
                (c.summary_text or "")[:200],
                "",
                "",
                "",
            ])
    print(f"[write] {csv_path}  ({len(in_scope)} rows; review with confidence-sorted spot-check)")


def main() -> None:
    hits = collect_govinfo_hits()
    candidates = dedupe_to_candidates(hits)
    reconcile_all(candidates)
    score_all(candidates)
    write_outputs(candidates)
    print("\nDone. Next: spot-check the top of data/candidates/review.csv.")


if __name__ == "__main__":
    main()
