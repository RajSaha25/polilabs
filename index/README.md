# index/

SQLite full-text + bibliographic index. The Layer-2 index that backs **`search_corpus`** and most metadata reads. Faster and simpler than the Kùzu graph for pure full-text + lookup queries.

## Files

- **`schema.py`** — Tables + FTS5 virtual tables. Schema includes: `bills`, `bill_versions`, `sections`, `cosponsors`, `committees`, `actions`, `bills_fts` (FTS5 over title/short_title/summary), `sections_fts` (FTS5 over section text), `corpus_meta`, `source_freshness`.
- **`parse_uslm.py`** — Bill XML → typed sections. Handles both USLM (modern) and pre-USLM bill formats. Walks `<section>` / `<subsection>` / `<paragraph>` hierarchies, extracts headings + enums + text + canonical citations.
- **`build.py`** — Destructive rebuild from `data/corpus/legislation/`. Re-parses every XML, populates SQLite + FTS, sets `corpus_meta` (version, criteria_version, timestamps).

## Build

```bash
python scripts/build_index.py    # ~30s, destructive
```

Output: `data/polilabs.db` (gitignored, regenerable).

## What's in the SQLite vs what's in Kùzu

| Thing | SQLite | Kùzu |
|---|---|---|
| Bill metadata (title, sponsor, dates, status) | ✓ | ✓ (subset) |
| Full-text search (FTS5) | ✓ | — |
| Section text (verbatim) | ✓ | — |
| Section tree (parent / child) | ✓ | ✓ |
| Citations (CITES_EXTERNAL → USC) | — | ✓ |
| DefinedTerm nodes | — | ✓ |
| AmendmentOperation nodes | — | ✓ |

SQLite is the canonical store for **searchable text** and **flat bibliographic data**. Kùzu is the canonical store for **typed relationships**. Some metadata is duplicated for query efficiency; `build_kuzu.py` reads from `data/corpus/` directly, not from SQLite, so they're independent regenerable views.

## parse_uslm.py is the upstream of upstreams

Every extractor in `graph/` operates on what `parse_uslm.py` emits. If parse_uslm skips a bill or a section, downstream extractors silently drop those rows. The `valid_section_ids` filter pattern in `graph/build_kuzu.py` was added because of this: a few USLM bills have two `<legis-body>` elements and parse_uslm returned only the first. Extractors that walked from the document root saw more sections than ended up in the index, producing dangling references.

If you're adding a bill format or fixing a parser gap, this is where to do it. Then rebuild both indexes.
