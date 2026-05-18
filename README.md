# polilabs

Agent-native queryable knowledge graph of US federal legislation. Built so any LLM agent — Claude, Cursor, ChatGPT, your own — can dig into the structured corpus and report back to legislative researchers without hallucinating.

v1 corpus: **191 AI-governance bills** from the 118th and 119th US Congresses (2023–present). v1 scope: legislation only — regulatory actions (FTC, NIST, Commerce) and executive orders are explicitly out.

## Product framing

The product is the **agent-facing API surface**, not the data files. Anyone can mirror Congress.gov XML. The value is:

1. **Reconciliation across sources** — bill metadata from Congress.gov, full text from GovInfo, U.S. Code from OLRC, all stitched together into one queryable graph.
2. **Agent-native primitives** — `find_bills_defining`, `get_amendments`, `resolve_citation`, etc. Aggregate queries are one tool call, not 50 sequential ones. Designed against documented LLM tool-use failure modes (N+1, context degradation, pagination truncation).
3. **Anti-hallucination guardrails** — every cited fact carries verbatim provenance from a tool response. Bills define terms locally; the same surface form ("AI", "frontier model") has different definitions across bills, and the API surfaces that divergence rather than collapsing it.

The agent doing the research is **NOT** polilabs' own agent. polilabs is the backend; the agent is yours.

## Three ways to drive it

```bash
# 1. Terminal REPL (Claude Opus 4.7 + the 12 polilabs tools)
python scripts/chat.py

# 2. Browser UI (same agent behind a Gradio chat)
python scripts/web.py

# 3. MCP stdio server — wire into Claude Desktop, Cursor, any MCP client
#    See "MCP setup" below.
python mcp_server.py
```

All three share the same agent tools and system prompt (defined in `agent/tools.py`).

## Setup

```bash
# Tier 1 data sources — sign up at console URLs, keys arrive instantly
#   Congress.gov:  https://api.congress.gov/sign-up/
#   GovInfo:       https://api.govinfo.gov/docs (api.data.gov)
#   Anthropic:     https://console.anthropic.com/
cp .env.example .env
# edit .env: paste in CONGRESS_GOV_API_KEY, GOVINFO_API_KEY, ANTHROPIC_API_KEY

# Install + smoke-test
python -m venv .venv && source .venv/bin/activate
pip install -e .
python scripts/smoke_test.py       # Tier 1 reachability
```

The v1 corpus (191 bills) is already committed under `data/corpus/legislation/`, so the only build step needed for normal use is the indexes:

```bash
python scripts/build_index.py          # ~30s — SQLite FTS index
python scripts/build_kuzu_index.py     # ~70s — Kùzu property graph
python scripts/kuzu_smoke_test.py      # verify graph structure
python scripts/api_smoke_test.py       # exercise the agent-facing API
```

`Re-fetching the corpus` from Congress.gov / GovInfo is a separate flow (`scripts/fetch_candidates.py` → `scripts/promote_corpus.py`); only needed if you're expanding scope or refreshing data.

## Agent tool surface (12 tools)

The agent gets these via `agent/tools.py`. Grouped by purpose:

**Discovery + scope**
- `search_corpus` — full-text search; returns ranked bill hits + `pagination_hint` that routes to aggregate tools when appropriate
- `corpus_coverage` — what's in / out of scope (use when answering scope questions or when a search returns nothing)

**Single-bill drill-in**
- `get_bill` — metadata + section table of contents (no body text)
- `get_section` — verbatim section text + canonical citation (cite this string *verbatim*)
- `get_defined_terms` — all terms one bill formally defines
- `get_amendments` — all amendments one bill makes

**Cross-reference + targeting**
- `get_citation_graph` — typed citation graph around a section (CITES_EXTERNAL → USC)
- `get_amendments_targeting` — operation-level detail of every amendment to a USC section
- `resolve_citation` — "Sec. 3(a)(1) of H.R. 1736, 119th Cong." → canonical section_id

**Aggregate / "list every bill that..." (added post-eval to fix N+1)**
- `find_bills_defining(term, ...)` — every bill defining a term, one call
- `find_bills_amending(statute_section_id)` — per-bill rollup of bills amending a USC section
- `find_definitions_of(term)` — every bill's verbatim definition of a term, side by side

The system prompt explicitly routes "which bills do X" questions to the aggregate tools. See `agent/tools.py:SYSTEM_PROMPT`.

## MCP setup

`mcp_server.py` exposes the same tools over MCP stdio. Add to your client's config:

```json
{
  "mcpServers": {
    "polilabs": {
      "command": "/absolute/path/to/polilabs/.venv/bin/python",
      "args": ["/absolute/path/to/polilabs/mcp_server.py"],
      "env": {
        "POLILABS_DB":   "/absolute/path/to/polilabs/data/polilabs.db",
        "POLILABS_KUZU": "/absolute/path/to/polilabs/data/polilabs.kuzu"
      }
    }
  }
}
```

The MCP server needs no Anthropic key — it just serves the tools. The client provides the LLM.

## Eval status

`eval/` ships a 13-query hand-curated test set across 6 categories (definition lookup, cross-bill consensus / divergence / targeting, amendment lookup, citation grounding, out-of-scope abstention). Each query has structured pass criteria scoring two failure modes:

- **Under-coverage** (low recall on set-valued queries; missing required substrings; abstaining when answer exists)
- **Over-confidence** (extra bills not in ground truth; forbidden substrings present; hallucinated citations)

Latest baseline: **12/13 passed** (92%), with 100% citation grounding (0 hallucinated). Single remaining failure is LLM variance on a stylistic precision check, not a code bug. See `eval/README.md` for the full eval contract.

```bash
python scripts/run_eval.py --dry-run   # verify wiring, no API call
python scripts/run_eval.py             # full run (~$5–10 in Opus spend)
python scripts/run_eval.py --query def_1736_ai
```

## Layout

Each folder has its own README explaining purpose, key files, and where it fits.

```
sources/      # Raw API clients (Congress.gov, GovInfo, OLRC) — see sources/README.md
ingest/       # Corpus build pipeline: search → score → reconcile → promote
index/        # SQLite FTS index — what most agent reads hit first
graph/        # Kùzu property graph — the agent-facing graph spine
api/          # Typed agent-facing API (the design contract is api/SPEC.md)
agent/        # Tool wrappers + system prompt shared by chat / web / MCP
eval/         # Eval harness: hand-curated queries + scorer + report
scripts/      # CLI entry points (build, smoke-test, chat, eval)
corpus/       # Locked inclusion criteria — what counts as "AI-governance"
research/     # Background research (landscape, design principles)
data/         # Committed corpus + gitignored indexes — see .gitignore

schema_design.md     # The property-graph ontology (~7,500 words) — read this first
                     # if you're touching graph/, api/, or eval/
```

## Design philosophy

- **Cross-check, don't wrap.** The product value is the reconciliation layer across sources. Each `sources/*.py` client is intentionally thin.
- **AI-native is what we build, not what we consume.** Raw USLM XML is authoritative but not agent-queryable. Making it queryable is the project.
- **Versioned law matters.** Scholars need "what did 5 U.S.C. § 552 say on date X." OLRC release points are in Tier 1 for that reason. (v1 stores one canonical version per bill; bitemporal versioning is in the schema, not yet wired.)
- **Anti-hallucination by construction.** Every claim returnable through the API carries a `provenance` field. Definitions are scoped to the bill that defines them — no global "AI system" node — so an agent reporting a definition can never mix bills.
- **Aggregate primitives over CRUD primitives.** The eval drove this: agents fail systematically on "search → loop → aggregate" patterns at ~20+ tool calls. Every N+1 pattern observed in the eval got an aggregate tool. See `eval/README.md` for the failure-mode analysis.

## For agents

If you're an LLM agent working in this repo, the canonical knowledge graph is `graphify-out/graph.json` (generated by [graphify](https://github.com/safishamsi/graphify)). The Claude Code PreToolUse hook will query it before exploration. Start there for code navigation, then read the relevant folder's README.

For the data model, read `schema_design.md` end-to-end before changing anything in `graph/`, `api/`, or `eval/`.
