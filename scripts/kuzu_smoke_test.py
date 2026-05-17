"""Smoke test for the polilabs Kùzu graph.

Runs a handful of structural Cypher queries against data/polilabs.kuzu
and prints results. Used to confirm that a fresh build looks healthy.

Build the index first:
    python scripts/build_kuzu_index.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import kuzu  # noqa: E402

from graph.build_kuzu import GRAPH_PATH  # noqa: E402


CHECKS: list[tuple[str, str]] = [
    ("bills in corpus",
     "MATCH (b:Bill) RETURN COUNT(b)"),
    ("sections in corpus",
     "MATCH (s:Section) RETURN COUNT(s)"),
    ("119th Congress bills",
     "MATCH (b:Bill {congress: 119}) RETURN COUNT(b)"),
    ("Tier A bills",
     "MATCH (b:Bill {tier: 'A'}) RETURN COUNT(b)"),
    ("primary sponsors via SPONSORED_BY",
     "MATCH ()-[r:SPONSORED_BY]->() RETURN COUNT(r)"),
    ("cosponsor edges via COSPONSORED_BY",
     "MATCH ()-[r:COSPONSORED_BY]->() RETURN COUNT(r)"),
    ("top-level sections (HAS_SECTION)",
     "MATCH ()-[r:HAS_SECTION]->() RETURN COUNT(r)"),
    ("section hierarchy edges (PARENT_OF)",
     "MATCH ()-[r:PARENT_OF]->() RETURN COUNT(r)"),
    ("citation edges (should be 0 in PR1)",
     "MATCH ()-[r:CITES_EXTERNAL]->() RETURN COUNT(r)"),
    ("defined terms (should be 0 in PR1)",
     "MATCH (d:DefinedTerm) RETURN COUNT(d)"),
]

SAMPLE_QUERIES: list[tuple[str, str]] = [
    ("H.R. 1736 (119th Cong.) title + sponsor",
     "MATCH (b:Bill {bill_id: 'bill:us/119/hr/1736'}) "
     "RETURN b.official_title, b.sponsor_display_name, b.tier"),
    ("H.R. 1736 top-level section headings",
     "MATCH (b:Bill {bill_id: 'bill:us/119/hr/1736'})-[:HAS_VERSION]->(:BillVersion)"
     "-[:HAS_SECTION]->(s:Section) RETURN s.enum, s.heading ORDER BY s.ordinal"),
    ("All bills cosponsored by Rep. Guest (bioguide G000591)",
     "MATCH (b:Bill)-[:COSPONSORED_BY]->(s:Sponsor {bioguide_id: 'G000591'}) "
     "RETURN b.bill_id, b.official_title LIMIT 5"),
    ("How many sections does each bill have? (top 5 by section count)",
     "MATCH (b:Bill)-[:HAS_VERSION]->(v:BillVersion)-[:HAS_SECTION]->(s:Section) "
     "RETURN b.bill_id, COUNT(s) AS section_count "
     "ORDER BY section_count DESC LIMIT 5"),
]


def main() -> int:
    if not GRAPH_PATH.exists():
        print(f"error: Kùzu DB not found at {GRAPH_PATH}. "
              f"Run `python scripts/build_kuzu_index.py` first.")
        return 2

    db = kuzu.Database(str(GRAPH_PATH))
    conn = kuzu.Connection(db)

    print("== Structural counts ==")
    failed = 0
    for label, query in CHECKS:
        try:
            r = conn.execute(query)
            val = r.get_next()[0] if r.has_next() else None
            print(f"  {label:<46} {val}")
        except Exception as e:
            print(f"  {label:<46} ERROR: {type(e).__name__}: {e}")
            failed += 1

    print()
    print("== Sample queries ==")
    for label, query in SAMPLE_QUERIES:
        print(f"\n  -- {label}")
        try:
            r = conn.execute(query)
            rows = []
            while r.has_next():
                rows.append(r.get_next())
            if not rows:
                print("     (no rows)")
            for row in rows[:10]:
                print(f"     {row}")
            if len(rows) > 10:
                print(f"     ... and {len(rows) - 10} more")
        except Exception as e:
            print(f"     ERROR: {type(e).__name__}: {e}")
            failed += 1

    print()
    if failed:
        print(f"!! {failed} check(s) failed")
        return 1
    print("OK — all structural checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
