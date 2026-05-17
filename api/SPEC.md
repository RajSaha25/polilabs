# polilabs agent-facing API — spec (v1 draft)

This is the contract the rest of the system is built against. Storage, ingestion, reconciliation, and eval all serve this surface. If an agent (LLM, MCP client, or the user) is going to query the corpus, it goes through these six primitives.

The implementation in `api/__init__.py` is currently stubs that raise `NotImplementedError`. This document explains the contract; the code locks the types.

## Design principles

These hold for every primitive. Implementations that violate them are wrong, regardless of how convenient the violation is.

1. **Hierarchical retrieval.** No primitive returns full bill text by default. The agent navigates: search → bill → section.
2. **Verbatim text always carries its canonical citation.** When text is returned, the canonical citation string is in the same payload. Agents must not reconstruct citations from prose.
3. **Stable opaque IDs.** Bill IDs and section IDs are stable strings. Round-tripping (result references ID → look up that ID) must work without fuzzy matching.
4. **Typed edges.** Citation relationships have a `type` (`amends`, `repeals`, `cites`, `references`). Untyped links are forbidden.
5. **Point-in-time queries.** Where a record is versioned, the primitive accepts an `as_of` date. Without it, "current" is returned and the response says so explicitly.
6. **Provenance per response.** Every response carries a `provenance` block: source(s), last verified, agreement score (where applicable).
7. **Empty distinct from out-of-scope.** A query returning zero hits must indicate whether it was *in-scope but empty* or *outside the corpus boundary*. Ambiguity here is the top hallucination cause.
8. **Token budgets are predictable.** No primitive returns unbounded text. Lists are paginated; bodies are length-capped or chunked.
9. **Honest unknowns.** When the corpus cannot answer, the primitive says so — does not return a best-effort guess.

## The six primitives

### `search_corpus`

Free-text search across the corpus. Returns ranked **lightweight hits** — never full text.

```python
search_corpus(
    query: str,
    *,
    date_range: tuple[date, date] | None = None,
    congresses: list[int] | None = None,
    tier: Literal["A", "B"] | None = None,
    streams: list[Stream] | None = None,  # default: ["legislation"]
    limit: int = 10,
    offset: int = 0,
) -> SearchResults
```

A `SearchHit` carries: `bill_id`, `title`, `short_title`, `summary` (≤1 paragraph), `sponsor`, `congress`, `introduced_date`, `tier`, `matched_keywords`, `relevance_score`, `provenance`.

`SearchResults` carries: `hits`, `total`, `query`, `coverage_note` (e.g., "412 bills, 118th–119th Congress, criteria v1.0"), `in_scope` (bool — distinguishes 0-hits-in-scope from query-out-of-scope).

### `get_bill`

Bill metadata and section table of contents. **No full text.**

```python
get_bill(bill_id: str) -> Bill
```

Returns: `bill_id`, `congress`, `bill_type`, `bill_number`, `title`, `short_title`, `sponsor`, `cosponsors`, `introduced_date`, `latest_action`, `status`, `tier`, `sections` (list of `SectionRef` — id + heading + version count), `versions` (list of `BillVersion` — introduced/engrossed/enrolled/etc.), `provenance`.

### `get_section`

Verbatim text of a single section, with canonical citation.

```python
get_section(section_id: str, *, as_of: date | None = None) -> Section
```

Returns: `section_id`, `bill_id`, `heading`, `text` (verbatim), `canonical_citation` (e.g., "Sec. 4(b)(2) of H.R. 5949, 118th Cong."), `parent_section_id`, `child_section_ids`, `version_date`, `version_label`, `is_current` (bool), `adjacency_summary` (citations in/out, with counts by type), `provenance`.

If `as_of` is set and no version of the section existed at that date, the response is explicit: `text` is `None`, `version_date` is `None`, and `provenance.notes` explains.

### `get_citation_graph`

Typed citation graph around a section. Bounded depth.

```python
get_citation_graph(
    section_id: str,
    *,
    depth: int = 1,
    edge_types: list[CitationType] | None = None,  # None = all
    direction: Literal["out", "in", "both"] = "both",
    max_nodes: int = 50,
) -> CitationGraph
```

Returns: `root_section_id`, `nodes` (list of `SectionRef` with metadata), `edges` (list of typed `CitationEdge`: `source_id`, `target_id`, `type`, `provenance`), `truncated` (bool — true if `max_nodes` was hit).

### `resolve_citation`

Parse a free-text citation string and return canonical IDs.

```python
resolve_citation(citation_string: str) -> ResolvedCitation
```

Returns: `input`, `resolved` (list of `ResolvedRef` — each carries `section_id`, `confidence`, `interpretation_note`), `is_ambiguous` (bool), `provenance`.

When ambiguous, all plausible candidates are returned with confidence scores — never a single best guess silently. The caller decides.

### `corpus_coverage`

Introspection. So an agent can say "I don't know" instead of confabulating coverage.

```python
corpus_coverage() -> CoverageReport
```

Returns: `corpus_version`, `criteria_version`, `last_updated`, `streams_in_scope` (e.g., `["legislation"]`), `streams_out_of_scope` (e.g., `["regulatory", "executive"]` with reasons), `date_range`, `congresses`, `bill_count_by_tier`, `source_freshness` (per source: last fetch timestamp), `known_gaps` (list of explicitly-acknowledged missing items).

## Provenance block

Every response carries:

```python
class Provenance:
    sources: list[str]              # e.g. ["govinfo:BILLS-118hr5949ih", "congress.gov:118/hr/5949"]
    last_verified: datetime
    agreement: AgreementScore | None  # None until Phase 4 multi-source cross-check
    notes: str | None               # human-readable caveat, e.g. "version inferred from latest_action"
```

## Error / unknown semantics

Primitives never raise on "not found in corpus." They return a typed response with `not_found` set and `provenance.notes` explaining. This is so the agent can distinguish "corpus says no" from "API broke." Genuine I/O errors do raise.

## What this spec deliberately does not cover

- Caching, rate limiting, or transport (these are implementation concerns).
- Embedding / semantic search internals (Phase 5; search_corpus is the surface, the implementation evolves).
- Multi-source disagreement resolution policy (Phase 4 design).
- LLM agent orchestration (out of scope — this is the tool surface the agent uses, not the agent).

## Versioning

This spec is versioned alongside the criteria. Breaking changes to any primitive's signature or return shape bump the spec version.

**API spec version:** v1.0 (draft, pre-implementation)
