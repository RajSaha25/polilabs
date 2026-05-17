"""Phase 1.3 — promote candidates to the structured corpus.

Reads:
  data/candidates/candidates_v1.jsonl  — output of fetch_candidates.py
  data/candidates/review.csv           — optional human-review decisions

For each candidate:
  - human review wins (`include=y` / `include=n`)
  - otherwise heuristic: include if centrality_score >= threshold (default 3.0)

For each included candidate, fetches the canonical bill version's USLM XML
and HTM from GovInfo, plus actions and cosponsors from Congress.gov, and
lays everything down under data/corpus/legislation/{bill_id}/.

Idempotent: bills already promoted are skipped unless --force.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from ingest.candidate import Candidate, PackageRef
from ingest.promote import (
    CORPUS_DIR,
    DEFAULT_HEURISTIC_THRESHOLD,
    decide_inclusion,
    load_review_csv,
    promote_one,
    write_corpus_index,
)
from sources.congress_gov import CongressGov


def load_candidates(path: Path) -> list[Candidate]:
    out: list[Candidate] = []
    with open(path) as f:
        for line in f:
            d = json.loads(line)
            d["versions"] = [PackageRef(**v) for v in d.get("versions", [])]
            out.append(Candidate(**d))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", default="data/candidates/candidates_v1.jsonl")
    ap.add_argument("--review", default="data/candidates/review.csv")
    ap.add_argument("--threshold", type=float, default=DEFAULT_HEURISTIC_THRESHOLD,
                    help="Heuristic centrality-score threshold for bills with no human decision")
    ap.add_argument("--force", action="store_true", help="Re-promote bills even if directory exists")
    ap.add_argument("--limit", type=int, default=None, help="Cap promotions (for testing)")
    args = ap.parse_args()

    candidates = load_candidates(Path(args.candidates))
    review = load_review_csv(Path(args.review))
    print(f"[load] candidates={len(candidates)}, reviewed={len(review)}")

    # Decide inclusion
    included: list[Candidate] = []
    decisions = {"human-y": 0, "human-n": 0, "heuristic-y": 0, "heuristic-n": 0}
    for c in candidates:
        include, tier, source = decide_inclusion(c, review.get(c.bill_id), threshold=args.threshold)
        if include:
            decisions[f"{source.split('-')[0]}-y" if "-" not in source else "human-y" if source == "human-review" else "heuristic-y"] = decisions.get(f"{source}-y", 0)
            key = "human-y" if source == "human-review" else "heuristic-y"
            decisions[key] = decisions.get(key, 0) + 1
            if tier:
                c.proposed_tier = tier
            included.append(c)
        else:
            key = "human-n" if source == "human-review" else "heuristic-n"
            decisions[key] = decisions.get(key, 0) + 1

    print(f"[decide] including {len(included)} of {len(candidates)} candidates")
    print(f"[decide] breakdown: {decisions}")

    if args.limit:
        included = included[: args.limit]
        print(f"[limit] capped to {len(included)} for this run")

    govinfo_api_key = os.environ["GOVINFO_API_KEY"]
    cgov = CongressGov()

    stats = {"added": 0, "skipped-exists": 0, "error": 0}
    last_log = time.time()
    for i, c in enumerate(included):
        result = promote_one(c, cgov=cgov, govinfo_api_key=govinfo_api_key, force=args.force)
        stats[result["status"]] = stats.get(result["status"], 0) + 1
        if result["status"] == "error":
            print(f"[error] {result['bill_id']}: {result.get('error', 'unknown')}")
        if time.time() - last_log > 3:
            print(f"[promote]   {i + 1}/{len(included)}  {stats}")
            last_log = time.time()

    # Build INDEX from what's now on disk (any pre-existing + this run's adds)
    on_disk = sorted([p.name for p in CORPUS_DIR.glob("*") if p.is_dir() and (p / "metadata.json").exists()])
    write_corpus_index([{"bill_id": b, "status": "added"} for b in on_disk])

    print(f"\n[done] {stats}  corpus_size={len(on_disk)}  index=data/corpus/INDEX.json")


if __name__ == "__main__":
    main()
