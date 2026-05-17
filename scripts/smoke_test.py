"""Smoke test for the three Tier 1 sources.

Run after putting your API keys in `.env`:
    python scripts/smoke_test.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv()

from sources.congress_gov import CongressGov
from sources.govinfo import GovInfo
from sources import olrc


def test_congress_gov() -> None:
    print("\n[Congress.gov] listing 1 recent bill from the 118th Congress")
    if not os.environ.get("CONGRESS_GOV_API_KEY"):
        print("  SKIP: CONGRESS_GOV_API_KEY not set in .env")
        return
    c = CongressGov()
    resp = c.list_bills(congress=118, limit=1)
    bill = resp["bills"][0]
    print(f"  OK: {bill['type']}{bill['number']} ({bill['congress']}) — {bill['title'][:80]}")


def test_govinfo() -> None:
    print("\n[GovInfo] listing collections")
    if not os.environ.get("GOVINFO_API_KEY"):
        print("  SKIP: GOVINFO_API_KEY not set in .env")
        return
    g = GovInfo()
    resp = g.list_collections()
    cols = [c["collectionCode"] for c in resp["collections"][:6]]
    print(f"  OK: first 6 collections — {cols}")


def test_olrc() -> None:
    print("\n[OLRC] checking release-points index is reachable")
    status = olrc.check_release_points_reachable()
    print(f"  OK: HTTP {status}")


if __name__ == "__main__":
    test_congress_gov()
    test_govinfo()
    test_olrc()
    print("\nDone.")
