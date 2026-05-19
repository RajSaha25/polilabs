# graph/

Kùzu property graph — the agent-facing graph spine. Backs everything graph-flavored in the API: citations, definitions, amendments, all the aggregate queries.

> Read `../schema_design.md` end-to-end before changing anything here. It's the property-graph ontology this folder implements.

## Files

- **`schema_kuzu.py`** — Node + relationship table DDL. 13 node tables (Bill, BillVersion, Section, Sponsor, Committee, Statute, StatuteSection, DefinedTerm, UnresolvedTermUse, AmendmentOperation, Extractor, ProvenanceRecord, Jurisdiction) + 16 rel tables. Declared upfront for schema stability.
- **`build_kuzu.py`** — Two-phase builder: (1) walk every bill XML and accumulate rows; (2) bulk insert via `UNWIND` in 2000-row chunks. ~70s to build from scratch. Destructive (drops + recreates the DB on each build).
- **`extract_citations.py`** — Walks `<external-xref legal-doc="usc">` elements in bill XML. Produces CITES_EXTERNAL edges from `Section` to `StatuteSection`. Skips `<quoted-block>` subtrees (they're amendatory payload, not the bill's own citations).
- **`extract_definitions.py`** — Finds "Definitions" containers, extracts surface_form from `<quote>`/`<term>`, classifies direct vs by_reference via regex (`has the meaning given...`). Produces DefinedTerm nodes + DEFINES + BY_REFERENCE edges.
- **`extract_amendments.py`** — One AmendmentOperation per `<quoted-block>`, operation type classified by surrounding text patterns ("by striking … and inserting", "by adding at the end", etc.). Produces AMENDS + TARGETS edges.

## Build pipeline

```bash
python scripts/build_kuzu_index.py    # ~70s — destructive rebuild from data/corpus/
python scripts/kuzu_smoke_test.py     # structural Cypher checks
```

Output goes to `data/polilabs.kuzu/` (a directory, not a single file — gitignored).

## What's in the graph (v1 corpus)

| Element | Count |
|---|---|
| Bills / BillVersions / Sections | 191 / 191 / 29,616 |
| Unique Sponsors | 411 |
| PARENT_OF / HAS_SECTION edges | 28,969 / 647 |
| SPONSORED_BY / COSPONSORED_BY | 191 / 688 |
| CITES_EXTERNAL (USC citations) | 646 across 137 bills, 172 unique USC targets |
| DefinedTerm nodes | 1,241 across 104 bills |
| DEFINES / BY_REFERENCE edges | 1,244 / 114 |
| AmendmentOperation nodes | 190 across 65 bills |
| AMENDS / TARGETS edges | 190 / 182 |

## Hard vs soft edges

Every edge has a `derivation` property:
- `mechanical` — extracted from XML structure (e.g. `<external-xref parsable-cite>`)
- `nlp_extracted` — pattern-matched from prose (e.g. amendment operation type)
- `llm_inferred` — derived by a language model (none in v1)
- `human_annotated` — checked by a person (none in v1)

Plus a `confidence` ∈ [0,1] and a `provenance` bundle (extractor_id, model_id if any, input_hash, verified_by, verified_at). Soft edges below a threshold are not surfaced to agents by default. See `schema_design.md` §6 for the policy.

## Known gaps (v1)

- USLM bill XML has 2 bills whose `<ref href>` citations aren't extracted yet (PR2.1 follow-up)
- Public Law citations (74 in corpus) and Section→Section internal citations not yet extracted (PR2.1)
- Definition use-site resolution (RESOLVED_TO / UnresolvedTermUse) not yet wired (PR3.1)
- `target_text_unverified=true` on every AmendmentOperation — OLRC USC text not yet ingested, so `before_text` can't be checked against the current statute. The synthesis function (Q5 in schema_design.md) will emit ConflictNote markers rather than picking a winner when verification runs.

## When you're adding an extractor

1. Add a `_accumulate_<thing>(valid_section_ids)` method to `Accum` in `build_kuzu.py`.
2. Filter outputs by `valid_section_ids` (parse_uslm has known gaps — some XML structures it skips; filtering here prevents dangling refs).
3. Update `schema_kuzu.py` if new node/edge types are needed.
4. Smoke-test with `scripts/kuzu_smoke_test.py`.
5. Add an API primitive in `api/_impl.py` that queries the new structure.
