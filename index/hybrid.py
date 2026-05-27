"""Hybrid retrieval: BM25 + dense embeddings combined by Reciprocal
Rank Fusion (RRF).

Why RRF over weighted-sum or learned-fusion:
  - No score-scale calibration. BM25 returns negative numbers (smaller =
    better in SQLite FTS5), cosine returns [-1, 1]. RRF works on ranks,
    so the scales don't have to be reconciled.
  - One free parameter (k, conventionally 60). No training data needed.
  - Robust to ties and to one side missing a hit entirely.

Why this fixes the eval Q5 failure:
  - "restrict advanced AI chip exports" matches the CLOUD AI Act and
    GAIN AI Act semantically (bge-small recognizes the concept) even
    though the bill titles avoid the surface phrase. BM25 misses; dense
    catches; RRF surfaces the bill.

Scope per-topic. The dense leg WHERE-filters by topic before computing
cosine, so cross-topic bleed (e.g. "agency" returning AI bills when the
caller is in the redistricting topic) is structurally impossible.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

import numpy as np

from .embeddings import EMBED_DIM, embed_query, load_topic_matrix


RRF_K = 60  # canonical constant from the original Cormack et al. paper

# bge-small-en-v1.5's absolute cosines are not directly meaningful as a
# threshold — even off-topic queries hit 0.5+ against typical legal text
# because the model has a strong "this is policy English" prior. A 0.4
# floor was useless; a 0.65 floor was brittle. Instead we gate the
# dense leg on BM25: dense rescues lexical-mismatch misses (Q5), but
# only WITHIN the universe BM25 has anchored. If BM25 finds zero
# in-topic hits, the topic doesn't contain the query — dense alone
# cannot invent matches.
#
# This is the same intuition as a join on a lexical key, with the
# dense leg expanding/reranking inside that join. Pure-semantic rescue
# (BM25 = 0 but dense > 0.75 in some section) is a future opt-in
# behind an explicit flag.


@dataclass
class HybridHit:
    """One ranked candidate after RRF fusion."""
    bill_id: str
    section_id: str | None        # may be None if only the bill-level
                                  # FTS hit matched
    score: float                  # fused RRF score (higher = better)
    bm25_rank: int | None         # 1-based, None if BM25 missed
    dense_rank: int | None        # 1-based, None if dense missed


# ---- BM25 leg ----

def _bm25_ranks(
    conn: sqlite3.Connection, fts_query: str, topic: str, limit: int = 200,
) -> tuple[dict[str, int], dict[str, str]]:
    """Run the existing FTS5 search, topic-scoped, and return rank dicts.

    Returns (bill_rank_by_id, best_section_for_bill). bill_rank_by_id maps
    bill_id → 1-based rank; the dict is in best-first order so iteration
    preserves rank.
    """
    bill_hits: dict[str, float] = {}
    section_for_bill: dict[str, str] = {}

    # Title-level hits
    for r in conn.execute(
        "SELECT bill_id, bm25(bills_fts) AS rank "
        "FROM bills_fts WHERE bills_fts MATCH ? AND topic = ? "
        "ORDER BY rank LIMIT ?",
        (fts_query, topic, limit),
    ):
        bill_hits[r["bill_id"]] = r["rank"]

    # Section-level hits — keep the best (most negative) per bill, plus
    # the section_id of the strongest section so we can surface it.
    for r in conn.execute(
        "SELECT section_id, bill_id, bm25(sections_fts) AS rank "
        "FROM sections_fts WHERE sections_fts MATCH ? AND topic = ? "
        "ORDER BY rank LIMIT ?",
        (fts_query, topic, limit * 4),  # more section rows because each bill has many
    ):
        bid = r["bill_id"]
        if bid not in bill_hits or r["rank"] < bill_hits[bid]:
            bill_hits[bid] = r["rank"]
            section_for_bill[bid] = r["section_id"]
        elif bid not in section_for_bill:
            section_for_bill[bid] = r["section_id"]

    if not bill_hits:
        return {}, {}

    # Convert score → rank. BM25 is negative-better, so sort ascending.
    sorted_bids = sorted(bill_hits.items(), key=lambda kv: kv[1])
    return {bid: i + 1 for i, (bid, _) in enumerate(sorted_bids)}, section_for_bill


# ---- Dense leg ----

# Module-level cache. Per-topic embeddings matrix is small (~30k × 384
# float32 ~= 46 MB for ai_governance). We hold it for the process
# lifetime so repeat queries don't pay the SQLite read cost.
_TOPIC_CACHE: dict[str, tuple[list[str], list[str], np.ndarray]] = {}


def _dense_ranks(
    conn: sqlite3.Connection, query_vec: np.ndarray, topic: str, limit: int = 200,
) -> tuple[dict[str, int], dict[str, str]]:
    """Compute cosine ranking against every section in the topic.

    Returns (bill_rank_by_id, best_section_for_bill). For each bill we
    keep the single best-scoring section as the "exemplar" — that's what
    drives the synced-highlight UX. The bill rank is the rank of its
    best section.
    """
    cached = _TOPIC_CACHE.get(topic)
    if cached is None:
        cached = load_topic_matrix(conn, topic)
        _TOPIC_CACHE[topic] = cached
    sids, bids, M = cached
    if M.shape[0] == 0:
        return {}, {}

    # query_vec is already unit-normalized; M is too. Cosine = dot.
    scores = M @ query_vec.astype(np.float32)
    # Top-N section indices (fast partial argsort via argpartition)
    n_consider = min(limit * 8, scores.shape[0])
    top_idx = np.argpartition(-scores, n_consider - 1)[:n_consider]
    top_idx = top_idx[np.argsort(-scores[top_idx])]

    bill_best_score: dict[str, float] = {}
    section_for_bill: dict[str, str] = {}
    for i in top_idx:
        bid = bids[i]
        sc = float(scores[i])
        cur = bill_best_score.get(bid)
        if cur is None or sc > cur:
            bill_best_score[bid] = sc
            section_for_bill[bid] = sids[i]

    sorted_bids = sorted(bill_best_score.items(), key=lambda kv: -kv[1])
    return {bid: i + 1 for i, (bid, _) in enumerate(sorted_bids)}, section_for_bill


# ---- RRF fusion ----

def hybrid_search(
    conn: sqlite3.Connection,
    *,
    query: str,
    fts_query: str,
    topic: str,
    limit: int = 25,
    k: int = RRF_K,
) -> list[HybridHit]:
    """Run hybrid retrieval and return up to `limit` fused candidates.

    `query` and `fts_query` come in separately because the caller has
    already normalized the FTS form (handling phrase-quotes, OR
    expansion, etc.); the dense embedding is computed off the raw user
    query so the model sees natural language.
    """
    bm25, bm25_sec = _bm25_ranks(conn, fts_query, topic, limit=limit * 4)

    # BM25-anchor gate: if the lexical leg returned zero in-topic hits,
    # the topic doesn't contain the query. Dense alone cannot invent
    # matches — bge-small's "general policy English" prior pushes most
    # off-topic queries to cosines ~0.5, which would otherwise flood
    # the result list. Pure-semantic rescue (e.g. "should AI development
    # pause?" when no bill uses those words) is a future opt-in;
    # without an explicit anchor we err on "no matches".
    if not bm25:
        return []

    q_vec = embed_query(query)
    dense, dense_sec = _dense_ranks(conn, q_vec, topic, limit=limit * 4)

    all_bids = set(bm25) | set(dense)

    out: list[HybridHit] = []
    for bid in all_bids:
        b_r = bm25.get(bid)
        d_r = dense.get(bid)
        # RRF: 1/(k + r). Missing-side contribution is 0.
        score = (1.0 / (k + b_r) if b_r is not None else 0.0) \
              + (1.0 / (k + d_r) if d_r is not None else 0.0)
        # Prefer the dense exemplar section when present (more
        # likely to be semantically tight); fall back to BM25's.
        section_id = dense_sec.get(bid) or bm25_sec.get(bid)
        out.append(HybridHit(
            bill_id=bid, section_id=section_id, score=score,
            bm25_rank=b_r, dense_rank=d_r,
        ))
    out.sort(key=lambda h: h.score, reverse=True)
    return out[:limit]


def clear_cache() -> None:
    """Drop the in-process topic-matrix cache. Used by build scripts
    after rebuilding the index so a same-process verification reads the
    fresh embeddings rather than stale ones."""
    _TOPIC_CACHE.clear()
