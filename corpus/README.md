# corpus/

Source of truth for **what counts as in-scope** for each polilabs topic corpus. The ingestion pipeline references these files; do not change them informally. One criteria file per topic (the "directory of inclusion-criteria files" the Future section below anticipated).

## Files

- **`inclusion_criteria.md`** — Locked v1.0 criteria for the `ai_governance` topic. Lists:
  - Required anchor keyword (at least one of: `AI` as standalone token, `artificial intelligence`, `machine learning`)
  - Expanding terms (facial recognition, generative AI, frontier model, automated decision systems)
  - Out-of-scope items (executive orders, regulatory actions, state legislation)
  - Tier definitions (A = primary AI-governance; B = substantial AI provisions)
- **`secret_congress_criteria.md`** — v1 criteria for the `secret_congress` topic: passage-dynamics exemplars (bipartisan laws quiet and loud, bipartisan bills that died, omnibus vehicles, party-line contrasts), the cluster vocabulary, and the rule that every seed entry is verified against its BILLSTATUS record before promotion.

## Why this file exists

Ingestion needs a falsifiable, version-controlled definition of "is this bill in scope?" Otherwise corpus expansion drifts and the eval's out-of-scope checks become subjective. The criteria are pinned to v1.0; any change requires bumping `corpus/inclusion_criteria.md`'s version and re-running candidate scoring (`scripts/fetch_candidates.py`).

## Where it's used

- `ingest/candidate.py` — anchor-gate check + centrality scoring
- `eval/queries.yaml` (oos_* category) — tests that the agent honors these limits and abstains when asked about out-of-scope items (EU AI Act, California SB 1047, EO 14110)
- `api/_impl.py::corpus_coverage()` — surfaces the criteria_version to agents

## Future: corpus expansion

When polilabs widens scope beyond AI-governance, this becomes a directory of inclusion-criteria files (one per topic corpus), each with its own version. The schema/code is corpus-agnostic — only the criteria file changes per domain.
