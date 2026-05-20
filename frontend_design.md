# polilabs Generative UI — Implementation Plan

## Context

polilabs has experimented with three frontends (Gradio, terminal REPL, MCP stdio) plus a bare FastAPI test page. All are plain prompt/answer chat. The goal now is a **generative/adaptive research UI** whose output reflects the *kind* of question asked, rather than a wall of text.

The core insight driving the design: because the backend queries a property graph where each node is a bill, **every query naturally produces a ranked list of source bills**. Researchers want two things per bill: the verbatim text they already trust, and a structured, prompt-aware decomposition that makes the dense text navigable.

Confirmed design decisions (with the user):
- **Built in-repo** as real code — React + Vite + TypeScript + Tailwind. Not Lovable.
- **Three-zone layout:** a left rail (ranked bill list + agent answer + prompt input), a center "Text" panel (verbatim bill text), a right "Decomp" panel (structured decomposition).
- **Decomp = structured extraction only.** It renders only mechanically-extracted graph data (definition cards, amendment diffs, citation lists, section outline). **No LLM-paraphrased prose** in the Decomp panel — readability comes from layout and interaction, not from rewriting the law. This preserves polilabs' anti-hallucination thesis.
- **Decomp form = side-by-side panels with synchronized highlighting.** Clicking a Decomp card highlights the matching verbatim span in the Text panel, and vice versa.

Intended outcome: a researcher asks a question, sees a ranked list of relevant bills, clicks/swipes between them, and reads each bill as verbatim text alongside a prompt-aware structured breakdown — with zero added hallucination surface.

## Architecture overview

Two backend access paths:
1. **Agent path** — `POST /chat` (SSE). Answers the question, produces the answer text and the ranked bill list. Needs a new `tool_result` event so the frontend can see structured tool output.
2. **REST path** — `GET /api/*`. Clicking/swiping a bill loads its data instantly and deterministically, with **no new agent turn** (no token cost, no latency).

Frontend lives in a new `web/` directory, built with Vite, served by FastAPI in production.

## Backend changes — `server.py`

### 1. Register all 12 tools
`server.py` currently registers only 5 (`search_corpus, get_bill, get_section, resolve_citation, corpus_coverage`). The agent must have all 12 or it cannot answer definition/amendment questions that drive the Decomp modes. Port the 12-tool set from `eval/runner.py` (lines ~155–242).

### 2. Recorder + `tool_result` SSE event
The Anthropic SDK `tool_runner` consumes tool results internally — the current stream never exposes them. Fix with the **recorder pattern already proven in `eval/runner.py`**:
- Inside `_stream_chat` (per-request, so state is request-scoped), create `recorded: list[dict]` and a `_record(name)` decorator that wraps each `tool_*` call, captures the return JSON, and appends `{name, args, result}` before returning to the runner.
- Build the 12 `@beta_tool` functions **inside** `_stream_chat` as closures over `recorded` (mirrors `eval/runner.py`). Not at module scope — that would share state across requests.
- In the `for msg in runner` loop, track `emitted_count`; after each message drain `recorded[emitted_count:]` and emit one `tool_result` SSE per new entry.

New event payload: `{"type": "tool_result", "name": str, "args": {...}, "result": {...parsed JSON...}}`. Five event types total: `text`, `tool_call`, `tool_result`, `done`, `error`.

### 3. REST endpoints (read-only, namespaced under `/api`)
Each wraps a `tool_*` function from `agent/tools.py` and returns `json.loads()` of its output — the same trick `/coverage` already uses. Section IDs contain `::`, so pass them as **query params**, not path segments.

| Route | Wraps | Returns |
|---|---|---|
| `GET /api/bill/{bill_id}` | `tool_get_bill` | `Bill` |
| `GET /api/bill/{bill_id}/sections` | new recursive aggregator | full nested section tree |
| `GET /api/bill/{bill_id}/defined_terms` | `tool_get_defined_terms` | `DefinedTermsResult` |
| `GET /api/bill/{bill_id}/amendments` | `tool_get_amendments` | `AmendmentsResult` |
| `GET /api/section?section_id=...` | `tool_get_section` | `Section` |
| `GET /api/citation_graph?section_id=...` | `tool_get_citation_graph` | `CitationGraph` |
| `GET /api/search?query=...` | `tool_search_corpus` | `SearchResults` |
| `GET /api/resolve?citation_string=...` | `tool_resolve_citation` | `ResolvedCitation` |
| `GET /api/coverage` | `tool_corpus_coverage` | `CoverageReport` (keep `/coverage` as alias) |

**New aggregator `GET /api/bill/{id}/sections`:** `get_bill` returns only top-level sections; the Decomp structure outline and Text panel need the full tree. Implement in `server.py`: call `get_bill`, then recursively `get_section` walking `child_section_ids`, return a nested structure. Wrap in `functools.lru_cache` keyed on `bill_id` (bill text is immutable in v1).

The four cross-corpus aggregates (`find_bills_defining`, `find_definitions_of`, `find_bills_amending`, `get_amendments_targeting`) are **not** REST routes — they answer questions, so they reach the UI only via `tool_result` SSE events.

### 4. Serving the frontend
- **Prod:** Vite builds to `web/dist/`; `app.mount("/", StaticFiles(directory="web/dist", html=True))` mounted **last** so `/api` and `/chat` take precedence. Tighten CORS `allow_origins` to the deployed origin.
- **Dev:** run `uvicorn server:app --reload` and `npm run dev` separately; `vite.config.ts` proxies `/api` and `/chat` to `:8000`.

## Frontend — `web/`

Stack: **React 18 + Vite + TypeScript + Tailwind**. Runtime deps kept minimal: `react`, `react-dom`, `zustand`, `clsx`, `embla-carousel-react` (bill-viewer swipe), `diff` (amendment word-diff).

```
web/
  vite.config.ts            # proxy /api + /chat → :8000
  src/
    main.tsx, App.tsx
    api/sse.ts              # SSE client
    api/rest.ts             # typed fetch wrappers for /api/*
    api/types.ts            # TS mirrors of api/types.py
    store/useAppStore.ts    # Zustand store
    decomp/selectMode.ts    # Decomp-mode selection
    decomp/highlight.ts     # substring-span matching
    components/...
```

### Component tree
```
<App>                       three-column grid shell
├── <LeftRail>
│   ├── <AgentAnswer>        streaming answer text
│   ├── <BillList>           ranked "agent view" list
│   │   └── <BillListItem>   short_title, sponsor, congress/tier badges, relevance bar
│   ├── <ToolTrace>          subdued tool-call list (optional)
│   └── <PromptBox>          pinned bottom; disabled while streaming
├── <BillViewer>             Embla carousel over the ranked bills
│   └── <BillSlide> → <BillPane>
│       ├── <TextPanel>      verbatim section text; <HighlightSpan> wrappers
│       └── <DecompPanel>
│           ├── <DecompModeTabs>     manual mode override
│           └── <DefinitionMode> | <AmendmentMode> | <CitationMode> | <StructureMode>
└── <CoverageFooter>         corpus version, bill counts, known_gaps
```

`BillViewer` owns the Embla instance; `selectedBillIndex` in the store is the single source of truth — clicking `BillList` calls `embla.scrollTo`, swiping writes the index back. `BillPane` triggers REST fetches on becoming active.

### State (Zustand — selector subscriptions matter because `text` deltas fire rapidly)
`history` (user turns only), `answerText`, `streaming`, `toolCalls`, `toolResults`, `rankedBills` (derived), `decompModeHint` (derived), `selectedBillIndex`, `billData` (keyed by bill_id, REST-fetched), `decompMode` (`'auto'` or override), `activeHighlight` (`{sectionId, text}`).

### SSE client
`POST /chat` via `fetch` + `ReadableStream` (lift the buffer-split-on-`\n\n` logic from `static/index.html`). On `done`, build `rankedBills` by scanning `toolResults` for bill-bearing shapes (`hits`/`matches`/`definitions`/`bills`/single `bill_id`), dedupe by `bill_id` preserving agent order; compute `decompModeHint`.

### Synced highlight (`decomp/highlight.ts`)
Each Decomp item carries a section ID (`defining_section_id` / `source_section_id`) and a verbatim string (`definition_text` / `before_text` / `after_text`). On card click, `setHighlight({sectionId, text})`; `TextPanel` `indexOf`-matches the string inside `Section.text` and wraps it in `<HighlightSpan>`. Reverse direction: pre-index section → anchored items, render those substrings as clickable `<mark>`. If the substring is not found, fall back to whitespace-collapsed match, then to scrolling-only — **never fabricate a highlight**.

### Decomp mode selection (`decomp/selectMode.ts`)
Priority by tool that answered: definitions tools → `definition`; amendment tools → `amendment`; `get_citation_graph` → `citation`; else → `structure` (default). User can override per-bill via `DecompModeTabs`.

## Build order

- **Phase 0 — backend (riskiest first):** 12 tools, recorder + `tool_result` event, REST routes incl. the `/sections` aggregator. Verify with `curl -N`.
- **Phase 1 — frontend skeleton + agent path:** Vite/TS/Tailwind scaffold, Zustand store, SSE client, three-column shell, `LeftRail` (answer + prompt + bill list).
- **Phase 2 — bill viewer + Text panel:** Embla carousel, REST fetch of `/sections`, verbatim text rendering, click + swipe nav.
- **Phase 3 — Decomp structure mode:** nested `SectionOutline`, click-to-scroll.
- **Phase 4 — Decomp definition + amendment modes + synced highlight** (second-riskiest: substring matching).
- **Phase 5 — citation mode, mode tabs, coverage footer, prod static mount, CORS lockdown.**

**Collaboration:** Phase 0 (backend) is the blocking prerequisite — it must land before any frontend phase can be built or tested, since the frontend depends on the `tool_result` SSE event and the `/api/*` routes. Once Phase 0 is merged, Phases 3–5 (the Decomp mode renderers — structure, definition, amendment, citation) are largely independent of each other and can be split across contributors. Phases 1–2 (skeleton, bill viewer) are a single connected slice and best owned by one person.

## Verification

Run: `uvicorn server:app --reload --port 8000` + `cd web && npm run dev`; open `http://localhost:5173`.

Backend isolation (before UI):
- `curl -N -X POST localhost:8000/chat -d '{"history":[],"message":"How does each bill define foundation model?"}'` → stream contains `tool_result` events whose `result` has a `definitions` array.
- `curl localhost:8000/api/bill/118-hr-5949/defined_terms` → `DefinedTermsResult` JSON.

End-to-end sample queries:
| Query | Expected Decomp mode | Expected UI |
|---|---|---|
| "How does each bill define foundation model?" | definition | ranked list of defining bills; `DefinitionCard`s with verbatim text; card click highlights span in Text panel |
| "What does H.R. 8516 change about existing law?" | amendment | `AmendmentCard`s with before/after word-diff; `target_text_unverified` banner shown |
| "What does Sec. 3(a)(1) of H.R. 1736 require?" | structure | bill loads, Text panel scrolls to that section |
| "What's NOT in this corpus?" | structure | answer streams; empty bill list; coverage footer accurate |

Correctness checklist: answer streams; ranked list matches agent order; click and swipe stay in sync; **switching bills issues REST fetches, not `/chat` calls** (verify in network tab); Decomp text is byte-identical to the bill's verbatim text (no paraphrase); highlight click scrolls and marks the right span.

## Risks

- **R1** — `get_bill` is top-level-only; the `/sections` recursive aggregator + `lru_cache` mitigates. Watch first-load latency on deep bills.
- **R2** — section IDs contain `::`; always query params, never bare path segments.
- **R3** — substring highlight can miss (truncation/whitespace normalization in primitives); degrade gracefully to scroll-only, never fabricate.
- **R4** — `Amendment.before_text` is often `null` (insert-only ops); `AmendmentCard` must render a no-prior-text state.
- **R5** — confirm navigation never triggers an agent turn.
- **R6** — frontend `history` must mirror `server.py`'s `_to_anthropic_history` (user turns only; never send the rendered answer back).
- **R8** — the SDK yields whole messages, so `text` arrives in paragraph-sized chunks, not per-token. Do not promise token-smooth streaming.

## Critical files

- `/Users/rajsaha/Code/polilabs/server.py` — 12 tools, recorder/`tool_result` SSE, REST routes, static mount
- `/Users/rajsaha/Code/polilabs/agent/tools.py` — reuse `tool_*` functions + `_dump` serializer (no change needed)
- `/Users/rajsaha/Code/polilabs/eval/runner.py` — reference recorder pattern to port into `_stream_chat`
- `/Users/rajsaha/Code/polilabs/api/types.py` — source of truth for `web/src/api/types.ts`
- `/Users/rajsaha/Code/polilabs/api/_impl.py` — confirms `get_bill` top-level-only behavior and section-ID formats
- New: `web/` tree, load-bearing files `web/src/store/useAppStore.ts`, `web/src/api/sse.ts`, `web/src/decomp/{selectMode,highlight}.ts`
