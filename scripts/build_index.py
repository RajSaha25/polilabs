"""Phase 2.1 — build data/polilabs.db from data/corpus/.

Re-runnable: destroys the existing DB and rebuilds from the corpus files.
The corpus files are the source of truth; the DB is a derived index.

P3 addition: after FTS5 populate, computes dense embeddings for every
section via fastembed (bge-small-en-v1.5) and stores them in
section_embeddings. Pass `--skip-embeddings` for fast iter on the
relational/FTS side without re-running the ~5-10 min encode pass.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from index.build import CORPUS_BASE, INDEX_PATH, build_index


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus-dir", default=str(CORPUS_BASE))
    ap.add_argument("--db", default=str(INDEX_PATH))
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--skip-embeddings", action="store_true",
                    help="Skip the dense-embedding step (fast iter on FTS side)")
    ap.add_argument("--embed-batch", type=int, default=16,
                    help="Embedding batch size. Smaller = less peak memory, "
                         "marginally slower. Default 16 is conservative for "
                         "an 8-16 GB laptop running other apps.")
    ap.add_argument("--embed-only", action="store_true",
                    help="Skip the relational/FTS rebuild and only run the "
                         "embedding pass against the existing DB. Use to "
                         "resume an interrupted embedding job.")
    args = ap.parse_args()

    if not args.embed_only:
        stats = build_index(
            corpus_dir=Path(args.corpus_dir),
            db_path=Path(args.db),
            verbose=not args.quiet,
        )
        print(f"\n[done relational] {stats}", flush=True)

    if args.skip_embeddings:
        print("[skip] dense embeddings (--skip-embeddings)", flush=True)
        return

    # Embedding pass runs against the now-populated DB. Lazy import so
    # --skip-embeddings users don't pay the fastembed import cost.
    # NB: no outer `with conn:` — embed_corpus owns its commit cadence
    # (per-batch), which makes interrupted runs cheaply resumable.
    from index.embeddings import embed_corpus
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        emb_stats = embed_corpus(
            conn, batch_size=args.embed_batch, verbose=not args.quiet,
        )
        print(f"[done embeddings] {emb_stats}", flush=True)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
