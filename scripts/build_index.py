"""Phase 2.1 — build data/polilabs.db from data/corpus/legislation/.

Re-runnable: destroys the existing DB and rebuilds from the corpus files.
The corpus files are the source of truth; the DB is a derived index.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from index.build import CORPUS_BASE, INDEX_PATH, build_index


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus-dir", default=str(CORPUS_BASE))
    ap.add_argument("--db", default=str(INDEX_PATH))
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    stats = build_index(
        corpus_dir=Path(args.corpus_dir),
        db_path=Path(args.db),
        verbose=not args.quiet,
    )

    print(f"\n[done] {stats}")


if __name__ == "__main__":
    main()
