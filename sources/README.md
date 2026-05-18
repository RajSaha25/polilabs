# sources/

Raw API clients — the input layer. **Intentionally thin.** The product value is in `ingest/` (reconciliation) and `api/` (agent surface), not here.

## Files

- **`congress_gov.py`** — Library of Congress API client. Bill metadata, sponsors, cosponsors, actions, vote records. Requires `CONGRESS_GOV_API_KEY` in `.env`. Free, 5,000 req/hr.
- **`govinfo.py`** — GPO GovInfo API client. Full text of bills, public laws, US Code as USLM XML. Requires `GOVINFO_API_KEY`. Free, generous rate limits.
- **`olrc.py`** — OLRC bulk-XML helpers. US Code release points (point-in-time snapshots of the entire USC). No auth — static ZIP downloads.

## Design

These are the **Tier 1 public-domain sources** — together they cover the bibliographic + full-text + statute layers needed to answer scholarly legislative questions. A future Tier 2 (Lexis, Bloomberg Law, Westlaw citator APIs) is intentionally deferred — see `research/landscape.md`.

Each client is intentionally minimal: thin request wrappers + response parsers, no caching, no retry logic, no reconciliation. Everything else (caching, dedup, version resolution, sponsor-ID reconciliation) lives in `ingest/`. The justification:

- **Easier to swap.** When Congress.gov releases v4 or a new endpoint, only this folder changes.
- **Easier to test.** Each client is a function-mock target. Reconciliation logic can be tested without hitting the real API.
- **Easier to audit.** Every API request the project makes is in 3 files.

## Where to add a new source

If you're adding a source (e.g. for Tier 2 commercial APIs, or for state-level data), follow the same pattern:

1. One file per upstream provider.
2. Each function returns a typed dict / dataclass — no raw `requests.Response`.
3. Caching, reconciliation, and dedup all live downstream in `ingest/`.
4. Document the auth requirement + rate limit in this README.

## What's not in here

- **Caching** → `data/cache/` (managed by `ingest/`)
- **Reconciliation** (picking the canonical version when GovInfo and Congress.gov disagree) → `ingest/reconcile.py`
- **Inclusion criteria** → `corpus/inclusion_criteria.md` + `ingest/candidate.py`
