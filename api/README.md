# api/

The agent-facing API. This is **the design contract** the rest of the system serves.

> If you're going to make non-trivial changes here, read `SPEC.md` end-to-end first. It's the spec; this README is the map.

## Files

- **`SPEC.md`** — Design contract. Lists the 9 invariants every primitive must hold (hierarchical retrieval, verbatim+citation together, typed edges, point-in-time, provenance, honest unknowns, etc.). The original 6 primitives are documented there; the 6 added later (post-eval aggregates + the definitions/amendments subsystem) follow the same invariants.
- **`types.py`** — Frozen dataclasses for every request/response shape. The agent surface is JSON; this layer is typed Python.
- **`_impl.py`** — All implementations. ~1200 LoC. Backed by **SQLite** (`data/polilabs.db`, full-text search + bibliographic metadata) and **Kùzu** (`data/polilabs.kuzu`, the property graph spine).
- **`__init__.py`** — Public exports. The agent layer (`agent/tools.py`) only imports from here, never from `_impl`.

## The 12 primitives

| Name | Backed by | One-line |
|---|---|---|
| `search_corpus` | SQLite FTS5 | Full-text search; returns ranked lightweight hits + `pagination_hint` |
| `get_bill` | SQLite | Metadata + section ToC; no body text |
| `get_section` | SQLite + Kùzu | Verbatim section text + canonical citation + adjacency summary |
| `get_citation_graph` | Kùzu | Typed citation graph around a section (depth=1) |
| `get_defined_terms` | Kùzu | All terms one bill formally defines |
| `get_amendments` | Kùzu | All amendments one bill makes |
| `get_amendments_targeting` | Kùzu | Operation-level detail of every amendment to a USC section |
| `resolve_citation` | SQLite | Parse "Sec. 3(a)(1) of H.R. 1736" → section_id |
| `corpus_coverage` | SQLite | What's in / out of scope, freshness, known gaps |
| `find_bills_defining` | Kùzu | **Aggregate**: every bill defining a term, one Cypher query |
| `find_bills_amending` | Kùzu | **Aggregate**: per-bill rollup of bills amending a USC section |
| `find_definitions_of` | Kùzu | **Aggregate**: every bill's definition of a term, side by side |

## Two storage backends

- **SQLite** (`data/polilabs.db`) — bibliographic metadata + FTS5 full-text. Built by `index/build.py`. Fast and simple; backs the discovery + drill-in primitives.
- **Kùzu** (`data/polilabs.kuzu`) — property graph. Built by `graph/build_kuzu.py`. Backs everything graph-flavored: citations, definitions, amendments, aggregates.

Both are gitignored and regenerable from `data/corpus/legislation/`. Build with `scripts/build_index.py` + `scripts/build_kuzu_index.py`.

## ID normalization

Three forms of bill IDs are accepted everywhere:
- Canonical: `119-hr-1736`
- URN: `bill:us/119/hr/1736`
- Prose: `H.R. 1736 (119th Cong.)` / `HR 1736 119th` / `H.R. 1736` (if unambiguous across congresses)

Statute IDs accept: URN `statute:us/usc/15/9401`, slash `15/9401`, prose `15 U.S.C. 9401`. Section IDs accept legacy `119-hr-1736::H7CA...` and URN `bill:us/119/hr/1736::H7CA...`. Normalization happens at the API boundary; downstream code sees one canonical form.

## Adding a new primitive

1. Define the request/response dataclasses in `types.py`.
2. Implement in `_impl.py`. If it's a graph query, write the Cypher; if it's metadata, hit SQLite.
3. Export from `__init__.py`.
4. Add a tool wrapper in `agent/tools.py` (description, schema, function entry).
5. Add a `@beta_tool` wrapper in `scripts/chat.py` and `eval/runner.py`.
6. Mention it in the `SYSTEM_PROMPT` if the routing matters.
7. Write an eval query in `eval/queries.yaml` that exercises it.
