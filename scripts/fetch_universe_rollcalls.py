"""Fetch party-split roll-call data for every universe bill that has
recorded-vote pointers. Totals only (no per-member positions) — member
detail stays a curated-corpus feature; the universe needs the
bipartisanship number, not 435 rows per vote.

Reads:  data/universe/bills_{congress}.jsonl.gz  (vote_refs field)
Writes: data/universe/rollcalls_{congress}.jsonl.gz  (committed)
Cache:  data/cache/rollcalls/  (raw vote XML, gitignored, resumable)

Volume: a Congress has ~1-2k roll calls per chamber; bills point at a
subset, deduped here by source URL, so a full pass is a few thousand
fetches (~20-40 min at the default sleep). Re-runs are cheap because of
the XML cache.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest.billstatus import fetch_rollcall  # noqa: E402
import ingest.billstatus as bs_mod  # noqa: E402

UNIVERSE_DIR = Path("data/universe")
CACHE_DIR = Path("data/cache/rollcalls")


def _cached_http_get(url: str, *, timeout: float = 30.0):
    """URL-keyed disk cache around the module's plain HTTP getter, so a
    re-run after an interruption refetches nothing."""
    key = hashlib.sha256(url.encode()).hexdigest()[:24]
    path = CACHE_DIR / f"{key}.xml"
    if path.exists():
        return path.read_bytes()
    raw = _orig_get(url, timeout=timeout)
    if raw is not None:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    return raw


_orig_get = bs_mod._http_get


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--congress", type=int, default=None)
    ap.add_argument("--sleep", type=float, default=0.25,
                    help="seconds between UNCACHED fetches")
    ap.add_argument("--limit", type=int, default=None,
                    help="cap number of unique vote URLs per congress (debug)")
    args = ap.parse_args()

    bs_mod._http_get = _cached_http_get  # route all vote fetches via cache

    bill_files = sorted(UNIVERSE_DIR.glob("bills_*.jsonl.gz"))
    if args.congress:
        bill_files = [p for p in bill_files if p.name == f"bills_{args.congress}.jsonl.gz"]

    for path in bill_files:
        congress = int(path.stem.split("_")[1].split(".")[0])
        out_path = UNIVERSE_DIR / f"rollcalls_{congress}.jsonl.gz"
        stats: Counter = Counter()

        # Collect refs, dedupe by URL but remember every bill pointing at it.
        url_refs: dict[str, dict] = {}
        url_bills: dict[str, set[str]] = {}
        with gzip.open(path, "rt") as f:
            for line in f:
                rec = json.loads(line)
                for ref in rec.get("vote_refs") or []:
                    url = ref.get("url")
                    if not url:
                        continue
                    url_refs.setdefault(url, ref)
                    url_bills.setdefault(url, set()).add(rec["bill_id"])

        urls = sorted(url_refs)
        if args.limit:
            urls = urls[: args.limit]
        print(f"[{congress}] {len(urls)} unique roll-call URLs "
              f"across {sum(len(b) for b in url_bills.values())} bill-vote links")

        rows: list[dict] = []
        t0 = time.time()
        for i, url in enumerate(urls, 1):
            was_cached = (CACHE_DIR / f"{hashlib.sha256(url.encode()).hexdigest()[:24]}.xml").exists()
            rc = fetch_rollcall(url_refs[url])
            if rc is None:
                stats["unresolved"] += 1
                continue
            base = rc.to_json()
            base.pop("members", None)
            d = base["totals_by_party"].get("D", {})
            r = base["totals_by_party"].get("R", {})
            for bill_id in sorted(url_bills[url]):
                rows.append({
                    "vote_id": f"{bill_id}::{rc.chamber}/{rc.congress}-{rc.session}/{rc.roll_number}",
                    "bill_id": bill_id,
                    "chamber": rc.chamber, "congress": rc.congress,
                    "session": rc.session, "roll_number": rc.roll_number,
                    "date": rc.date, "question": rc.question, "result": rc.result,
                    "vote_type": rc.vote_type,
                    "yea_total": rc.yea_total, "nay_total": rc.nay_total,
                    "dem_yea": d.get("yea"), "dem_nay": d.get("nay"),
                    "rep_yea": r.get("yea"), "rep_nay": r.get("nay"),
                    "bipartisan_support": rc.bipartisan_support,
                    "bipartisan_label": rc.bipartisan_label,
                    "source_url": rc.source_url,
                })
            stats["votes"] += 1
            if i % 200 == 0:
                print(f"  {i}/{len(urls)}  votes={stats['votes']} unresolved={stats['unresolved']} "
                      f"({time.time()-t0:.0f}s)")
            if not was_cached:
                time.sleep(args.sleep)

        rows.sort(key=lambda v: v["vote_id"])
        with gzip.open(out_path, "wt", compresslevel=9) as f:
            for v in rows:
                f.write(json.dumps(v, separators=(",", ":")) + "\n")
        print(f"[{congress}] wrote {len(rows)} bill-vote rows -> {out_path} "
              f"({dict(stats)}, {time.time()-t0:.0f}s)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
