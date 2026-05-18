# ingest/

Corpus build pipeline: **discover → score → reconcile → promote**. Turns raw GovInfo + Congress.gov data into the curated `data/corpus/legislation/` directory that everything downstream reads from.

You typically run this only when **expanding the corpus** or **refreshing data**. For normal use, the v1 corpus is already committed; just build the indexes (`scripts/build_index.py` + `scripts/build_kuzu_index.py`).

## Files

- **`govinfo_search.py`** — Full-text search against GovInfo for candidate bills matching the AI-governance criteria.
- **`candidate.py`** — Anchor-gate check (does the bill contain a required keyword from `corpus/inclusion_criteria.md`?) + centrality scoring (how many AI-related terms? where do they appear?). Outputs `data/candidates/candidate_v1.jsonl`.
- **`reconcile.py`** — For each candidate, pull rich metadata from Congress.gov (sponsor, cosponsors, actions, latest version). Cached to `data/cache/` to avoid hammering the API.
- **`promote.py`** — Takes candidates from `candidate_v1.jsonl` + review CSV (`data/candidates/review.csv`) and writes them to `data/corpus/legislation/{congress}-{type}-{number}/` with `bill.xml` + `metadata.json`. This is the committed output that everything downstream reads.

## Pipeline

```bash
# Phase 1.1 — discover and score
python scripts/fetch_candidates.py
# Phase 1.2 — manually review data/candidates/review.csv if needed
# Phase 1.3 — promote
python scripts/promote_corpus.py
# Phase 2 — rebuild indexes
python scripts/build_index.py
python scripts/build_kuzu_index.py
```

## Design

- **Cross-check, don't wrap** (see top-level README). `sources/*.py` are thin clients; `ingest/` is where the actual reconciliation happens — picking which version is canonical, resolving sponsor IDs, deduping across sources.
- **Cached aggressively.** Both GovInfo and Congress.gov rate-limit; `data/cache/` is the deduper. Cache is gitignored.
- **Review step is intentional.** `data/candidates/review.csv` exists so a human can sanity-check anchor-keyword hits before promotion. Some bills mention "AI" in passing without being about AI; the candidate-score heuristic catches most of these but the CSV is the final filter.

## Corpus boundaries (v1)

- Bills only (not regulatory actions, executive orders, or state legislation — see `corpus/inclusion_criteria.md`)
- 118th and 119th Congresses (2023–present)
- Anchor keyword required (`AI`, `artificial intelligence`, or `machine learning`)

Expanding any of those means: (a) update inclusion_criteria.md, (b) re-run candidate scoring, (c) review the new candidates, (d) promote, (e) rebuild indexes.
