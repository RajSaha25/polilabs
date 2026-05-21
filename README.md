# polilabs

Agent-native queryable knowledge graph of US federal legislation. Built so any LLM agent — Claude, Cursor, ChatGPT, your own — can dig into the structured corpus and report back to legislative researchers without hallucinating.

v1 corpus: **191 AI-governance bills** from the 118th and 119th US Congresses (2023–present). v1 scope: legislation only — regulatory actions (FTC, NIST, Commerce) and executive orders are explicitly out.

## Product framing

The product is the **agent-facing backend** — the tool surface and the HTTP API — not the data files. Anyone can mirror Congress.gov XML. The value is:

1. **Reconciliation across sources** — bill metadata from Congress.gov, full text from GovInfo, U.S. Code from OLRC, all stitched together into one queryable graph.
2. **Agent-native primitives** — `find_bills_defining`, `get_amendments`, `resolve_citation`, etc. Aggregate queries are one tool call, not 50 sequential ones. Designed against documented LLM tool-use failure modes (N+1, context degradation, pagination truncation).
3. **Anti-hallucination guardrails** — every cited fact carries verbatim provenance from a tool response. Bills define terms locally; the same surface form ("AI", "frontier model") has different definitions across bills, and the API surfaces that divergence rather than collapsing it.

The agent doing the research is **NOT** polilabs' own agent. polilabs is the backend; the agent is yours.

## What the backend is made of

Two queryable stores, one tool layer, and four ways to reach it.

```
data/corpus/        authoritative USLM XML (191 bills, committed)
   │
   ├─ index/        SQLite + FTS5     full-text search
   └─ graph/        Kùzu property graph   bills · sections · defined terms ·
                                          amendments · citations, all typed
   │
api/  +  agent/     12 typed, agent-native tools over both stores
   │
   ├─ scripts/chat.py     terminal REPL        (Claude Opus 4.7 + the tools)
   ├─ scripts/web.py      Gradio chat UI
   ├─ mcp_server.py       MCP stdio server     (Claude Desktop, Cursor, …)
   └─ server.py           FastAPI HTTP API     (SSE agent + REST — see below)
```

Every store is derived from `data/corpus/`; the corpus itself is committed, so a normal checkout only has to build the two indexes.

## Driving polilabs

```bash
# 1. Terminal REPL — Claude Opus 4.7 wired to the 12 polilabs tools
python scripts/chat.py

# 2. Gradio chat — the same agent behind a browser chat UI
python scripts/web.py

# 3. MCP stdio server — wire the tools into Claude Desktop, Cursor, any MCP client
python mcp_server.py

# 4. FastAPI HTTP API — SSE agent endpoint + a read-only REST surface
make backend          # uvicorn server:app on :8000
```

All four share the same tools and system prompt (`agent/tools.py`). The HTTP API is what the reference web frontends (`web/`, `web-design-a/`) are built on.

## Setup

```bash
# Tier 1 data sources — sign up at the console URLs, keys arrive instantly
#   Congress.gov:  https://api.congress.gov/sign-up/
#   GovInfo:       https://api.govinfo.gov/docs  (api.data.gov)
#   Anthropic:     https://console.anthropic.com/
cp .env.example .env
# edit .env: paste in CONGRESS_GOV_API_KEY, GOVINFO_API_KEY, ANTHROPIC_API_KEY

make install          # create .venv, install Python + web deps
make build            # build the SQLite + Kùzu indexes from data/corpus/ (~100s, one time)
```

The v1 corpus (191 bills) is committed under `data/corpus/legislation/`, so `make build` is the only build step. It runs `scripts/build_index.py` (SQLite FTS, ~30s) and `scripts/build_kuzu_index.py` (Kùzu graph, ~70s); `scripts/kuzu_smoke_test.py` and `scripts/api_smoke_test.py` verify the result.

Re-fetching the corpus from Congress.gov / GovInfo is a separate flow (`scripts/fetch_candidates.py` → `scripts/promote_corpus.py`), only needed to expand scope or refresh data.

## The 12-tool agent surface

The tools every driver shares. Each returns JSON with verbatim `provenance`.

**Discovery + scope**
- `search_corpus` — full-text search; ranked bill hits + a `pagination_hint` that routes to aggregate tools when appropriate
- `corpus_coverage` — what's in / out of scope (use when answering scope questions or when a search returns nothing)

**Single-bill drill-in**
- `get_bill` — metadata + section table of contents (no body text)
- `get_section` — verbatim section text + canonical citation (cite this string *verbatim*)
- `get_defined_terms` — every term a bill formally defines
- `get_amendments` — every amendment a bill makes

**Cross-reference + targeting**
- `get_citation_graph` — typed citation graph around a section (CITES_EXTERNAL → USC)
- `get_amendments_targeting` — operation-level detail of every amendment to a USC section
- `resolve_citation` — "Sec. 3(a)(1) of H.R. 1736, 119th Cong." → canonical section_id

**Aggregate / "list every bill that…"** (added post-eval to kill N+1 loops)
- `find_bills_defining(term, …)` — every bill defining a term, one call
- `find_bills_amending(statute_section_id)` — per-bill rollup of bills amending a USC section
- `find_definitions_of(term)` — every bill's verbatim definition of a term, side by side

## HTTP API — `server.py`

`make backend` starts a FastAPI server on `:8000` with **two access paths**: an SSE agent endpoint, and a read-only REST surface that hits the tools directly with no model turn (instant, no token cost).

### Auth — per-user accounts

The agent path and the REST surface are **login-only** — `/chat` spends Anthropic tokens on every call, so an anonymous caller must not reach it. Auth is self-hosted (`auth/`): accounts live in a standalone SQLite DB (`data/auth.db`), passwords are bcrypt-hashed, and sessions are stateless JWTs.

| Endpoint | Body / auth | Returns |
|---|---|---|
| `POST /auth/signup` | `{email, password}` | `{token, user}` — creates an account |
| `POST /auth/login` | `{email, password}` | `{token, user}` — exchanges credentials for a token |
| `GET /auth/me` | `Authorization: Bearer <token>` | `{id, email}` — token probe |

Send the token as `Authorization: Bearer <token>` on `/chat` and every `/api/*` request; a missing or expired token returns `401`. `/auth/*`, `/health`, `/coverage` and the test page at `/` stay public. Set `POLILABS_JWT_SECRET` in `.env` (see `.env.example`); if unset, a secret is generated and persisted to `data/auth_secret.key` on first run. Verify the auth surface with `python scripts/auth_smoke_test.py`.

### Agent path — `POST /chat` (Server-Sent Events)

Body: `{ "message": str, "history": [{role, content}, …] }`. Streams the agent's run as SSE frames, each `data: {json}`:

| Event | Payload | Meaning |
|---|---|---|
| `text` | `delta` | a chunk of answer text |
| `tool_call` | `name`, `args` | the agent invoked a tool |
| `tool_result` | `name`, `args`, `result` | that tool's parsed JSON output |
| `done` | — | turn complete |
| `error` | `message` | a friendly error string (raw exceptions are logged server-side, never streamed) |

The `tool_result` events expose the structured data behind the answer — a frontend can render ranked bills, definition cards, or amendment diffs straight from them.

### REST path — `GET /api/*` (read-only, no model turn)

Click or navigate to a bill and load its data deterministically, instantly, for free. Each endpoint wraps a tool and returns its JSON.

| Endpoint | Returns |
|---|---|
| `GET /api/search?query=&tier=&congress=&limit=` | ranked bill hits |
| `GET /api/bill/{bill_id}` | bill metadata + section table of contents |
| `GET /api/bill/{bill_id}/sections` | full nested section tree with verbatim text |
| `GET /api/bill/{bill_id}/defined_terms` | every term the bill defines |
| `GET /api/bill/{bill_id}/amendments` | every amendment the bill makes |
| `GET /api/section?section_id=&as_of=` | one section's verbatim text + citation |
| `GET /api/citation_graph?section_id=&direction=&max_nodes=` | typed citation graph around a section |
| `GET /api/resolve?citation_string=` | parse a free-text citation → canonical IDs |
| `GET /api/coverage` | corpus coverage snapshot |
| `GET /health` | liveness + whether the DB and API key are configured |
| `GET /` | `static/index.html` — a minimal test page that exercises `/chat` |

Every `/api/*` route requires a Bearer token (see **Auth** above); `/health` and `/` do not. Section IDs contain `::`, so they travel as **query params**, never path segments. CORS is open (`allow_origins=["*"]`) for dev — lock it to your origin before deploying anywhere public.

### Building a frontend on it

The API is frontend-agnostic — parse the SSE stream for the agent path, `fetch` the REST endpoints for navigation. Two reference frontends ship in-repo against this same backend: `web/` (React + Vite + TypeScript) and `web-design-a/` (a parallel design experiment). `make dev` runs the backend plus the `web/` Vite dev server together on `:5173`.

## Drive it from any MCP client

`mcp_server.py` exposes the same 12 tools over MCP stdio. Add to your client's config:

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

- **Under-coverage** — low recall on set-valued queries; missing required substrings; abstaining when an answer exists
- **Over-confidence** — extra bills not in ground truth; forbidden substrings; hallucinated citations

Latest baseline: **12/13 passed** (92%), with 100% citation grounding (0 hallucinated). The single failure is LLM variance on a stylistic precision check, not a code bug. See `eval/README.md` for the full eval contract.

```bash
make eval                              # full run (~$5–10 in Opus spend)
python scripts/run_eval.py --dry-run   # verify wiring, no API call
python scripts/run_eval.py --query def_1736_ai
```

## Repo layout

Each folder has its own README explaining purpose, key files, and where it fits.

```
sources/      # Raw API clients (Congress.gov, GovInfo, OLRC) — intentionally thin
ingest/       # Corpus build pipeline: search → score → reconcile → promote
index/        # SQLite FTS index — what most agent reads hit first
graph/        # Kùzu property graph — the agent-facing graph spine
api/          # Typed agent-facing API (the design contract is api/SPEC.md)
agent/        # Tool wrappers + system prompt shared by every driver
server.py     # FastAPI HTTP API — SSE /chat + the /api/* REST surface
mcp_server.py # MCP stdio server — the 12 tools for any MCP client
eval/         # Eval harness: hand-curated queries + scorer + report
scripts/      # CLI entry points (build, smoke-test, chat, eval)
web/          # Reference frontend (React + Vite + TypeScript)
web-design-a/ # Parallel frontend design experiment
corpus/       # Locked inclusion criteria — what counts as "AI-governance"
research/     # Background research (landscape, design principles)
data/         # Committed corpus + gitignored indexes — see .gitignore

schema_design.md   # The property-graph ontology (~7,500 words) — read this first
                   # if you're touching graph/, api/, or eval/
```

## Design philosophy

- **Cross-check, don't wrap.** The product value is the reconciliation layer across sources. Each `sources/*.py` client is intentionally thin.
- **AI-native is what we build, not what we consume.** Raw USLM XML is authoritative but not agent-queryable. Making it queryable is the project.
- **Versioned law matters.** Scholars need "what did 5 U.S.C. § 552 say on date X." OLRC release points are in Tier 1 for that reason. (v1 stores one canonical version per bill; bitemporal versioning is in the schema, not yet wired.)
- **Anti-hallucination by construction.** Every claim returnable through the API carries a `provenance` field. Definitions are scoped to the bill that defines them — no global "AI system" node — so an agent reporting a definition can never mix bills.
- **Aggregate primitives over CRUD primitives.** The eval drove this: agents fail systematically on "search → loop → aggregate" patterns at ~20+ tool calls. Every N+1 pattern observed in the eval got an aggregate tool. See `eval/README.md` for the failure-mode analysis.

## For agents

If you're an LLM agent working in this repo, the canonical knowledge graph is `graphify-out/graph.json`. Start there for code navigation, then read the relevant folder's README.

For the data model, read `schema_design.md` end-to-end before changing anything in `graph/`, `api/`, or `eval/`.
