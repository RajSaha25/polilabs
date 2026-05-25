"""One-shot backfill: stamp `topic` into every metadata.json under
data/corpus/legislation/. Idempotent — re-running is a no-op.

The v1 corpus is the 191-bill AI-governance corpus, so every existing
metadata.json gets topic="ai_governance". The P2 redistricting pipeline
will populate data/corpus/redistricting/ with topic="redistricting"
directly via ingest/promote.py (no backfill needed for new ingest).

Run once after merging the schema-plumbing PR; the change is recorded in
the metadata.json files themselves and committed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

CORPUS_DIR = Path("data/corpus/legislation")
DEFAULT_TOPIC = "ai_governance"


def main() -> int:
    if not CORPUS_DIR.is_dir():
        print(f"corpus dir missing: {CORPUS_DIR}", file=sys.stderr)
        return 1

    updated = 0
    already = 0
    missing = 0
    for d in sorted(CORPUS_DIR.iterdir()):
        if not d.is_dir():
            continue
        mp = d / "metadata.json"
        if not mp.exists():
            missing += 1
            continue
        meta = json.loads(mp.read_text())
        if meta.get("topic") == DEFAULT_TOPIC:
            already += 1
            continue
        meta["topic"] = DEFAULT_TOPIC
        # Preserve key order intent: drop topic in right after stream so
        # diffs are minimal and humans see it next to its sibling fields.
        ordered: dict = {}
        for k, v in meta.items():
            if k == "topic":
                continue
            ordered[k] = v
            if k == "stream":
                ordered["topic"] = DEFAULT_TOPIC
        if "topic" not in ordered:
            ordered["topic"] = DEFAULT_TOPIC
        mp.write_text(json.dumps(ordered, indent=2, default=str) + "\n")
        updated += 1

    print(f"backfill done: updated={updated}, already_set={already}, missing_metadata={missing}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
