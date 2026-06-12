"""Build the bill-status UNIVERSE layer: one compact record for every
law-track bill (hr, s, hjres, sjres) of the configured Congresses, parsed
from GovInfo BILLSTATUS bulk-data zips.

Why a universe layer exists (2026-06 scope expansion):
  The curated topic corpora carry full text for ~230 bills. Everything
  else was invisible, so the agent could not answer even "did H.R. X
  pass?" for an out-of-corpus bill, and corpus-level claims ("bipartisan
  laws pass quietly") had no denominator. The universe layer gives every
  bill a lightweight status record — outcome, sponsor, party-split votes
  (enriched separately), title variants for alias resolution — WITHOUT
  full text. Full text stays curated; coverage of *facts about bills*
  becomes total for the covered Congresses.

Inputs:  data/cache/billstatus_zips/BILLSTATUS-{congress}-{type}.zip
         (downloaded by this script with --download, or by hand; ~12 zips)
Outputs: data/universe/bills_{congress}.jsonl.gz   (committed; compact)

The SQLite index build (`index/build_universe_tables.py`) reads the
jsonl.gz artifacts; the zips themselves are gitignored cache.

Record schema (one JSON object per line):
  bill_id, congress, bill_type, bill_number, title, all_titles[],
  introduced_date, policy_area, sponsor{bioguideId,fullName,party,state,
  district}, cosponsor_counts{D,R,I,total}, latest_action{date,text},
  outcome{outcome,public_law,events[<=12]}, vote_refs[{chamber,congress,
  session,roll_number,date,url}], origin_chamber, subjects_top[<=12]
"""
from __future__ import annotations

import argparse
import gzip
import io
import json
import sys
import time
import zipfile
from collections import Counter
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest.billstatus import derive_outcome, parse_billstatus  # noqa: E402

ZIP_DIR = Path("data/cache/billstatus_zips")
OUT_DIR = Path("data/universe")
CONGRESSES = [117, 118, 119]
BILL_TYPES = ["hr", "s", "hjres", "sjres"]
ZIP_URL = "https://www.govinfo.gov/bulkdata/BILLSTATUS/{congress}/{btype}/BILLSTATUS-{congress}-{btype}.zip"
MAX_EVENTS = 12
MAX_SUBJECTS = 12


def download_zips(*, force: bool = False) -> None:
    ZIP_DIR.mkdir(parents=True, exist_ok=True)
    for congress in CONGRESSES:
        for btype in BILL_TYPES:
            dest = ZIP_DIR / f"BILLSTATUS-{congress}-{btype}.zip"
            if dest.exists() and not force:
                continue
            url = ZIP_URL.format(congress=congress, btype=btype)
            print(f"[dl] {url}")
            r = requests.get(url, timeout=600)
            r.raise_for_status()
            dest.write_bytes(r.content)


def _compact_record(status: dict) -> dict:
    """Squeeze a parsed BILLSTATUS into the universe record shape."""
    outcome = derive_outcome(status, rollcalls=[])
    cos = Counter((c.get("party") or "?") for c in status.get("cosponsors", []))
    events = outcome["events"][:MAX_EVENTS]
    return {
        "bill_id": f"{status['congress']}-{status['bill_type']}-{status['bill_number']}",
        "congress": status["congress"],
        "bill_type": status["bill_type"],
        "bill_number": status["bill_number"],
        "title": status["title"],
        "all_titles": status.get("all_titles", []),
        "introduced_date": status["introduced_date"],
        "origin_chamber": status["origin_chamber"],
        "policy_area": status["policy_area"],
        "sponsor": status["sponsor"],
        "cosponsor_counts": {
            "D": cos.get("D", 0), "R": cos.get("R", 0),
            "I": cos.get("I", 0) + cos.get("ID", 0),
            "total": sum(cos.values()),
        },
        "latest_action": status["latest_action"],
        "outcome": {
            "outcome": outcome["outcome"],
            "public_law": outcome["public_law"],
            "events": events,
        },
        "vote_refs": status["recorded_vote_refs"],
        "subjects_top": status["subjects"][:MAX_SUBJECTS],
    }


def build(congress: int) -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"bills_{congress}.jsonl.gz"
    stats: Counter = Counter()
    t0 = time.time()
    records: list[tuple[tuple, dict]] = []

    for btype in BILL_TYPES:
        zpath = ZIP_DIR / f"BILLSTATUS-{congress}-{btype}.zip"
        if not zpath.exists():
            print(f"[warn] missing {zpath} — run with --download first; skipping")
            stats["missing_zips"] += 1
            continue
        with zipfile.ZipFile(zpath) as zf:
            names = [n for n in zf.namelist() if n.endswith(".xml")]
            for name in names:
                try:
                    status = parse_billstatus(zf.read(name))
                    rec = _compact_record(status)
                except Exception:
                    stats["parse_errors"] += 1
                    continue
                # A few zip members are auxiliary documents that parse but
                # carry no bill identity (e.g. dtd descriptors); a record
                # without type+number would collapse into a garbage
                # '117--0' bill_id.
                if not rec["bill_type"] or not rec["bill_number"]:
                    stats["skipped_no_identity"] += 1
                    continue
                sort_key = (rec["bill_type"], rec["bill_number"])
                records.append((sort_key, rec))
                stats[f"bills_{btype}"] += 1
                stats["bills"] += 1

    # Deterministic order so the committed artifact diffs cleanly.
    records.sort(key=lambda kv: kv[0])
    with gzip.open(out_path, "wt", compresslevel=9) as f:
        for _, rec in records:
            f.write(json.dumps(rec, separators=(",", ":")) + "\n")

    stats["seconds"] = int(time.time() - t0)
    size_mb = out_path.stat().st_size / 1e6
    print(f"[{congress}] {stats['bills']} bills -> {out_path} ({size_mb:.1f} MB) "
          f"in {stats['seconds']}s  errors={stats['parse_errors']}")
    return dict(stats)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--download", action="store_true", help="fetch missing zips first")
    ap.add_argument("--congress", type=int, default=None, help="build one congress only")
    args = ap.parse_args()

    if args.download:
        download_zips()

    congresses = [args.congress] if args.congress else CONGRESSES
    overall: Counter = Counter()
    for c in congresses:
        overall.update(build(c))
    print(f"[done] {dict(overall)}")
    return 0 if overall.get("missing_zips", 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
