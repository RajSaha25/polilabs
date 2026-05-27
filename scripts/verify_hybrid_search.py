"""Smoke / regression tests for P3's hybrid retrieval.

This script is intentionally lightweight — it verifies that the hybrid
path RUNS end-to-end (model loads, query embeds, BM25 + dense both fire,
RRF combines, topic filter holds), not that it OUTPERFORMS pure BM25.

The outperformance check requires a completed embedding pass; this
smoke test runs in seconds against whatever embeddings happen to be in
section_embeddings at the moment. If the table is empty or partial,
hybrid_search degrades gracefully to BM25-only — that path is exercised
here too.

Run after `make build` finishes (or any partial embed run):
    python -m scripts.verify_hybrid_search

Tests:
  1. Smoke — search_corpus returns hits without crashing.
  2. Topic filter — querying topic A for a topic B keyword returns
     zero hits (structural filter, not soft rank).
  3. Partial-state report — shows how many sections are embedded so
     a reader knows whether the dense leg is contributing.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import api


def _print_hits(label: str, hits, limit: int = 5) -> None:
    print(f"\n  {label}:")
    if not hits:
        print("    (no hits)")
        return
    for h in hits[:limit]:
        print(f"    {h.bill_id:<14} score={h.relevance_score:>7.4f}  "
              f"{(h.title or '')[:60]}")


def test_smoke_ai() -> bool:
    """The AI-governance search runs and returns hits for a basic query."""
    print("\n[smoke] AI corpus: 'frontier model'")
    r = api.search_corpus("frontier model", topic="ai_governance", limit=5)
    _print_hits("hits", r.hits)
    if r.in_scope and r.hits:
        print("  PASS (search ran end-to-end, returned hits)")
        return True
    print(f"  FAIL ({r.in_scope=}, {len(r.hits)} hits)")
    return False


def test_smoke_redistricting() -> bool:
    """Redistricting search runs and returns hits."""
    print("\n[smoke] redistricting corpus: 'voting rights'")
    r = api.search_corpus("voting rights", topic="redistricting", limit=5)
    _print_hits("hits", r.hits)
    if r.in_scope and r.hits:
        print("  PASS")
        return True
    print(f"  FAIL ({r.in_scope=}, {len(r.hits)} hits)")
    return False


def test_topic_leak() -> bool:
    """Topic filter is structural: 'gerrymander' must return zero
    ai_governance bills. The filter is a SQL WHERE clause, not a
    rank penalty, so this is a hard guarantee."""
    print("\n[topic leak] 'gerrymander' @ ai_governance must be empty")
    r = api.search_corpus("gerrymander", topic="ai_governance", limit=5)
    _print_hits("ai_governance hits", r.hits)
    if not r.hits:
        print("  PASS (zero leak)")
        return True
    print(f"  FAIL ({len(r.hits)} hits leaked)")
    return False


def test_topic_partition() -> bool:
    """A query that touches both topics should return DIFFERENT bill
    sets per topic (bill_ids are disjoint by topic by construction)."""
    print("\n[partition] 'agency review' returns disjoint bill sets")
    ai = api.search_corpus("agency review", topic="ai_governance", limit=5)
    rd = api.search_corpus("agency review", topic="redistricting", limit=5)
    _print_hits("ai_governance", ai.hits)
    _print_hits("redistricting", rd.hits)
    ai_set = {h.bill_id for h in ai.hits}
    rd_set = {h.bill_id for h in rd.hits}
    overlap = ai_set & rd_set
    if ai.hits and rd.hits and not overlap:
        print("  PASS (disjoint sets)")
        return True
    if not ai.hits or not rd.hits:
        print(f"  INCONCLUSIVE (one side empty)")
        return False
    print(f"  FAIL (overlap: {overlap})")
    return False


def _embed_state() -> None:
    print("\n[state] section_embeddings coverage:")
    conn = sqlite3.connect("data/polilabs.db")
    by_topic = dict(conn.execute(
        "SELECT topic, COUNT(*) FROM section_embeddings GROUP BY topic"
    ).fetchall())
    section_totals = dict(conn.execute(
        "SELECT b.topic, COUNT(*) FROM sections s "
        "JOIN bills b ON b.bill_id = s.bill_id GROUP BY b.topic"
    ).fetchall())
    conn.close()
    for topic in sorted(set(by_topic) | set(section_totals)):
        embedded = by_topic.get(topic, 0)
        total = section_totals.get(topic, 0)
        pct = (100.0 * embedded / total) if total else 0.0
        print(f"  {topic:<16} {embedded:>6}/{total:<6} sections embedded ({pct:.1f}%)")
    if not by_topic:
        print("  (no embeddings — hybrid_search degrades to BM25-only)")
    print("  (note: incomplete coverage means the dense leg under-contributes; "
          "quality tests should wait for a completed embed pass)")


def main() -> int:
    print("=" * 70)
    print("polilabs P3 hybrid-search smoke test")
    print("=" * 70)
    _embed_state()
    results = [
        test_smoke_ai(),
        test_smoke_redistricting(),
        test_topic_leak(),
        test_topic_partition(),
    ]
    passed = sum(results)
    total = len(results)
    print(f"\n{'=' * 70}")
    print(f"smoke summary: {passed}/{total} passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
