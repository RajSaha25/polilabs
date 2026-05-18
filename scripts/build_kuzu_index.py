"""CLI: build the polilabs Kùzu graph from data/corpus/.

Usage:
    python scripts/build_kuzu_index.py [--db data/polilabs.kuzu] [--quiet]

This is destructive — the existing graph DB at the target path is
deleted before rebuild. The corpus directory (data/corpus/) is the
source of truth; the graph store is regenerable.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# Allow `python scripts/build_kuzu_index.py` from repo root without install.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from graph.build_kuzu import CORPUS_DIR, GRAPH_PATH, build_graph  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--corpus", type=Path, default=CORPUS_DIR,
                    help=f"Corpus root (default: {CORPUS_DIR})")
    ap.add_argument("--db", type=Path, default=GRAPH_PATH,
                    help=f"Kùzu DB path (default: {GRAPH_PATH})")
    ap.add_argument("--quiet", action="store_true", help="Suppress progress output")
    args = ap.parse_args()

    if not args.corpus.exists():
        print(f"error: corpus dir not found: {args.corpus}", file=sys.stderr)
        return 2

    started = time.monotonic()
    stats = build_graph(corpus_dir=args.corpus, db_path=args.db, verbose=not args.quiet)
    elapsed = time.monotonic() - started

    print()
    print(f"  bills indexed         {stats['bills_in_db']:>6}")
    print(f"  bill versions         {stats['bill_versions_in_db']:>6}")
    print(f"  sections              {stats['sections_in_db']:>6}")
    print(f"  sponsors (unique)     {stats['sponsors_in_db']:>6}")
    print(f"  statute sections      {stats['statute_sections_in_db']:>6}  (citation targets, lazily MERGEd)")
    print(f"  HAS_SECTION edges     {stats['has_section_edges']:>6}")
    print(f"  PARENT_OF edges       {stats['parent_of_edges']:>6}")
    print(f"  SPONSORED_BY edges    {stats['sponsored_by_edges']:>6}")
    print(f"  COSPONSORED_BY edges  {stats['cosponsored_by_edges']:>6}")
    print(f"  CITES_EXTERNAL edges  {stats['cites_external_edges']:>6}  "
          f"(across {stats['bills_with_citations']} bills)")
    print(f"  parse / insert errors {stats['parse_errors']:>6}")
    print(f"  xml format mix        {stats['format']}")
    print(f"  elapsed               {elapsed:>6.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
