"""Backfill billstatus.json (outcome + roll-call votes + actions +
cosponsors) for every bill already in data/corpus/, across all topics.

Entirely keyless — GovInfo BILLSTATUS bulk data plus House Clerk /
Senate LIS roll-call XML. Never modifies metadata.json or bill.xml; the
enrichment lives in a sibling billstatus.json that the index build
prefers when present.

Most AI-governance bills never reached a floor vote, so for them this
mainly adds: a derived outcome (died_in_committee / pending / ...), the
full action trail, and cosponsor/subject data where the original
Congress.gov enrichment was skipped.

Resumable: BILLSTATUS responses are cached under data/cache/billstatus/
and bill dirs with an existing billstatus.json are skipped unless
--force.
"""
from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest.billstatus import enrich_bill_dir  # noqa: E402

CORPUS_BASE = Path("data/corpus")


def _iter_bill_dirs(base: Path):
    for topic_dir in sorted(p for p in base.iterdir() if p.is_dir()):
        for bill_dir in sorted(p for p in topic_dir.iterdir() if p.is_dir()):
            if (bill_dir / "metadata.json").exists():
                yield topic_dir.name, bill_dir


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--topic", help="only this topic subdir (e.g. legislation, redistricting)")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--sleep", type=float, default=0.3)
    args = ap.parse_args()

    dirs = [
        (topic, d) for topic, d in _iter_bill_dirs(CORPUS_BASE)
        if args.topic is None or topic == args.topic
    ]
    if args.limit:
        dirs = dirs[: args.limit]
    print(f"[backfill] {len(dirs)} bill dirs")

    stats: Counter[str] = Counter()
    for i, (topic, d) in enumerate(dirs, 1):
        try:
            res = enrich_bill_dir(d, force=args.force)
        except Exception as e:
            res = f"error:{type(e).__name__}"
        stats[res] += 1
        if res not in ("added", "skipped-exists"):
            print(f"  ! {d.name} ({topic}): {res}")
        if i % 25 == 0:
            print(f"  {i}/{len(dirs)}  {dict(stats)}")
        if res == "added" and i < len(dirs):
            time.sleep(args.sleep)

    print(f"[done] {dict(stats)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
