# polilabs

Queryable, citation-accurate database of US federal legislation for scholars.

The v1 wedge corpus is **AI-governance** legislation: federal bills since ~2017 that touch AI, machine learning, algorithmic decision-making, or related policy. The architecture is built to generalize to any domain.

## Tier 1 data sources (this commit)

| Source | Role | Auth | Cost |
|---|---|---|---|
| **Congress.gov API** | Bill metadata, sponsors, votes, actions | API key | Free |
| **GovInfo API** | Full text of bills, public laws, US Code | API key | Free |
| **OLRC bulk XML** | US Code as point-in-time release points | None | Free |

Together these are the public-domain spine. A future Tier 2 layer (Lexis / Bloomberg / Westlaw citator APIs) is intentionally deferred — see project notes.

## Setup

### 1. Get API keys (instant)

- **Congress.gov**: sign up at <https://api.congress.gov/sign-up/>. Key arrives by email in seconds. Rate limit: 5,000 req/hr.
- **GovInfo**: sign up at <https://api.govinfo.gov/docs> (the "Get API Key" link goes to api.data.gov). Key shown immediately and emailed.

OLRC needs no key — it's just static ZIP downloads of US Code release points.

### 2. Drop keys into `.env`

```bash
cp .env.example .env
# then edit .env and paste in the two keys
```

### 3. Install and smoke-test

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .
python scripts/smoke_test.py
```

You should see one bill from the 118th Congress, six GovInfo collection codes, and an HTTP 200 from the OLRC release-points index.

## Drive it from a chat

After building the index (`python scripts/build_index.py`), put your `ANTHROPIC_API_KEY` in `.env` and run:

```bash
python scripts/chat.py
```

You get an interactive REPL backed by Claude Opus 4.7 with the six polilabs primitives wired in as tools. The system prompt constrains the agent to cite verbatim from `get_section` (no reconstructed citations) and to acknowledge corpus-scope limits honestly. Try things like:

- "What bills in the 119th Congress address frontier model safety?"
- "What does Sec. 3(a)(1) of H.R. 1736 actually require?"
- "Are there any bills about facial recognition in federal contracting?"
- "What's NOT in this corpus?"

## Drive it from a browser

Same agent, same tools, behind a Gradio chat UI:

```bash
python scripts/web.py
```

Opens at <http://localhost:7860>. Add `--share` for a public *.gradio.live tunnel — convenient for sending a link, but proceed with caution since it exposes your Anthropic-billed quota.

## Drive it from any MCP client

`mcp_server.py` exposes the same six primitives over MCP stdio. Add to your MCP client's server config:

```json
{
  "mcpServers": {
    "polilabs": {
      "command": "/absolute/path/to/polilabs/.venv/bin/python",
      "args": ["/absolute/path/to/polilabs/mcp_server.py"],
      "env": {
        "POLILABS_DB": "/absolute/path/to/polilabs/data/polilabs.db"
      }
    }
  }
}
```

The MCP server reads the same SQLite index — no Anthropic API key needed for the server itself.

## Build the graph index

In parallel with the SQLite index, polilabs maintains a Kùzu property-graph index that backs the schema in `schema_design.md`. PR1 shipped the bibliographic spine; PR2 adds the citation graph; definitions and amendments are PR3–PR4.

```bash
python scripts/build_kuzu_index.py        # ~70s on the v1 corpus
python scripts/kuzu_smoke_test.py         # structural Cypher checks + sample queries
```

Output goes to `data/polilabs.kuzu` (gitignored, regenerable from `data/corpus/`). The build is destructive: the existing graph is deleted and rebuilt.

What populates after PR3 (191 bills):

| Element | Count |
|---|---|
| Bills / BillVersions / Sections | 191 / 191 / 29,616 |
| Unique Sponsors | 411 |
| `PARENT_OF` / `HAS_SECTION` edges | 28,969 / 647 |
| `SPONSORED_BY` / `COSPONSORED_BY` | 191 / 688 |
| `CITES_EXTERNAL` (USC citations) | 646, across 137 bills, 172 unique USC targets |
| `DefinedTerm` nodes | 1,241, across 104 bills |
| `DEFINES` / `BY_REFERENCE` edges | 1,244 / 114 |

The agent-facing API reads from Kùzu for `get_citation_graph`, `get_defined_terms`, and `get_section`'s `adjacency_summary`; bibliographic primitives (`get_bill`, `search_corpus`, etc.) still read from SQLite. Section IDs round-trip between legacy (`119-hr-1736::H7CA...`) and URN (`bill:us/119/hr/1736::H7CA...`) forms transparently.

## Layout

```
sources/                # raw source clients (input layer)
  congress_gov.py       # Library of Congress API
  govinfo.py            # GPO GovInfo API
  olrc.py               # OLRC US Code bulk-XML helpers
ingest/                 # corpus build pipeline
  govinfo_search.py     # full-text search for candidates
  candidate.py          # anchor gate + centrality scoring
  reconcile.py          # Congress.gov metadata pull (cached)
  promote.py            # promote candidates → structured corpus
index/                  # Layer-2 SQLite index (backs FTS5 + the legacy API)
  schema.py             # tables + FTS5
  parse_uslm.py         # bill XML → sections
  build.py              # destructive rebuild from corpus
graph/                  # Kùzu property-graph index (the new spine)
  schema_kuzu.py        # node + rel table DDL per schema_design.md
  build_kuzu.py         # two-phase collect → bulk-UNWIND insert
api/                    # agent-facing API surface
  SPEC.md               # design contract
  __init__.py           # public exports
  types.py              # typed dataclasses
  _impl.py              # SQLite-backed implementations (Kùzu port in later PRs)
agent/                  # tool wrappers shared by chat + MCP
  tools.py              # serializers, schemas, system prompt
scripts/
  smoke_test.py         # Tier 1 reachability
  fetch_candidates.py   # Phase 1.1 — GovInfo search → ranked CSV
  promote_corpus.py     # Phase 1.3 — promote to data/corpus/
  build_index.py        # Phase 2.1 — build data/polilabs.db (SQLite)
  build_kuzu_index.py   # build data/polilabs.kuzu (graph spine)
  kuzu_smoke_test.py    # structural Cypher checks against the Kùzu DB
  api_smoke_test.py     # exercise the six primitives
  chat.py               # Phase 5 — Claude chat REPL
mcp_server.py           # Phase 5 — MCP stdio server
corpus/
  inclusion_criteria.md # locked AI-governance criteria v1.0
research/               # prior research (landscape, notes)
schema_design.md        # the property-graph ontology this repo is built on
data/
  candidates/           # candidate_v1.jsonl + review.csv (committed)
  corpus/legislation/   # promoted bills (committed)
  cache/                # API response cache (gitignored)
  polilabs.db           # SQLite index (gitignored, regenerable)
  polilabs.kuzu         # Kùzu graph (gitignored, regenerable)
```

## Design notes

- **Cross-check, don't wrap.** The product value comes from the reconciliation layer across sources — not from being a wrapper on any single API. Each client here is intentionally thin.
- **AI-native is what we build, not what we consume.** Raw GovInfo XML is authoritative but not agent-queryable; making it queryable is the project.
- **Versioned law matters.** Scholars need "what did the law say on date X." That's why OLRC release points are in Tier 1, not the live Congress.gov bill text alone.
