# agent/

Tool wrappers + system prompt — the **only** layer that's specific to LLM-agent consumption. Everything below this (`api/`, `graph/`, `index/`) is plain Python.

## Files

- **`tools.py`** — The whole agent surface. Three things live here:
  1. **Tool wrappers** (`tool_*`): thin functions that call `api.*` primitives, serialize the typed dataclass response to JSON, and return errors as structured `{"error": ...}` JSON rather than raising. So the agent sees a parseable failure, never a stack trace.
  2. **Metadata** (`TOOL_DESCRIPTIONS`, `TOOL_SCHEMAS`, `TOOL_FUNCTIONS`) used by the MCP server.
  3. **`SYSTEM_PROMPT`** — the agent's operating instructions. Defines tool-routing rules ("prefer aggregate primitives over search→loop"), citation-fidelity rules, and abstention rules. Updating this is the highest-leverage agent behavior change.
- **`__init__.py`** — re-exports.

## Who imports it

- `scripts/chat.py` — terminal REPL (wraps each tool with `@beta_tool` for the Anthropic SDK)
- `scripts/web.py` — Gradio UI (same wrappers, different transport)
- `mcp_server.py` — MCP stdio server (uses `TOOL_DESCRIPTIONS` + `TOOL_SCHEMAS`)
- `eval/runner.py` — re-wraps tools with a per-query recorder so the scorer can see what the agent actually saw

All four ship the **same 12 tools and same system prompt**. If you're tuning agent behavior, change `tools.py` once and re-run the eval.

## Tool surface

12 tools, grouped:

| Group | Tools |
|---|---|
| Discovery / scope | `search_corpus`, `corpus_coverage` |
| Single-bill drill-in | `get_bill`, `get_section`, `get_defined_terms`, `get_amendments` |
| Cross-reference | `get_citation_graph`, `get_amendments_targeting`, `resolve_citation` |
| **Aggregate (added post-eval)** | `find_bills_defining`, `find_bills_amending`, `find_definitions_of` |

Aggregate tools were added after the eval showed agents fail systematically on "list every bill that X" questions modelled as search→loop. See `eval/README.md` for the failure analysis.

## When you're changing agent behavior

1. **Tool routing** ("when should the agent use tool X vs Y?") — edit `SYSTEM_PROMPT`, not the tools.
2. **Tool capability** ("agent needs a new query shape") — add a primitive in `api/_impl.py` first, then expose it here.
3. **Response shape** ("agent struggles to parse field X") — change the dataclass in `api/types.py`; `_dump()` re-serializes automatically.

Re-run the eval (`python scripts/run_eval.py`) after any change. Single-query test: `python scripts/run_eval.py --query <id>`.
