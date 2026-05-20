"""FastAPI backend — the 12-tool polilabs agent, exposed over HTTP.

Two access paths for a frontend:

  1. Agent path — POST /chat (SSE). Answers a question; streams the
     answer text, the tool calls the agent made, and the structured
     tool *results* (so the UI can render decomposition panels).
  2. REST path — GET /api/*. Deterministic, read-only data fetches with
     no agent turn (no token cost, no latency) — used when the user
     clicks/navigates between bills.

POST /chat SSE event types: text, tool_call, tool_result, done, error.

REST endpoints (all read-only, JSON):
  GET /api/search?query=...                  search_corpus
  GET /api/bill/{bill_id}                     get_bill (top-level ToC)
  GET /api/bill/{bill_id}/sections            full nested section tree
  GET /api/bill/{bill_id}/defined_terms       get_defined_terms
  GET /api/bill/{bill_id}/amendments          get_amendments
  GET /api/section?section_id=...             get_section (verbatim text)
  GET /api/citation_graph?section_id=...      get_citation_graph
  GET /api/resolve?citation_string=...        resolve_citation
  GET /api/coverage                           corpus_coverage
  GET /coverage  /health  /                   legacy aliases + test page

Section IDs contain '::', so they travel as query params, never path
segments.

Run:
    python server.py
    # or: uvicorn server:app --reload --port 8000
"""
from __future__ import annotations

import functools
import json
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent))
load_dotenv(Path(__file__).resolve().parent / ".env")

import anthropic
import uvicorn
from anthropic import beta_tool
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from agent.tools import (
    SYSTEM_PROMPT,
    tool_corpus_coverage,
    tool_find_bills_amending,
    tool_find_bills_defining,
    tool_find_definitions_of,
    tool_get_amendments,
    tool_get_amendments_targeting,
    tool_get_bill,
    tool_get_citation_graph,
    tool_get_defined_terms,
    tool_get_section,
    tool_resolve_citation,
    tool_search_corpus,
)


# ---- FastAPI app ----


app = FastAPI(
    title="polilabs",
    description="Agent backend for the polilabs AI-governance corpus.",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # DEV ONLY — lock to your frontend origin in prod
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatMessageIn(BaseModel):
    role: str = Field(description="'user' or 'assistant'")
    content: str


class ChatRequest(BaseModel):
    message: str = Field(description="The new user message")
    history: list[ChatMessageIn] = Field(default_factory=list, description="Prior turns (user/assistant text only)")


def _to_anthropic_history(history: list[ChatMessageIn]) -> list[dict]:
    """Drop assistant text from the history — re-sending raw assistant turns
    without their matching tool_use/tool_result block pairs would 400 the API.
    Keeping user turns preserves conversational context; Claude re-calls
    tools as needed each turn.
    """
    return [{"role": m.role, "content": m.content} for m in history if m.role == "user"]


def _sse(event: dict[str, Any]) -> str:
    """Format one Server-Sent Event line."""
    return f"data: {json.dumps(event, default=str)}\n\n"


def _friendly_error(exc: Exception) -> str:
    """Map an exception to a short, human-readable message for the UI.

    The raw exception is logged server-side; the client never sees a
    stack-trace fragment or a raw API error dict — a research tool
    should fail legibly."""
    status = getattr(exc, "status_code", None)
    if status == 529:
        return ("The model service is temporarily overloaded. "
                "Please retry in a moment.")
    if status == 429:
        return "Rate limit reached. Please wait a few seconds and retry."
    if status in (401, 403):
        return "The server's API key was rejected — check ANTHROPIC_API_KEY."
    if isinstance(exc, (anthropic.APIConnectionError, anthropic.APITimeoutError)):
        return "Couldn't reach the model service. Check the connection and retry."
    if isinstance(status, int) and status >= 500:
        return "The model service hit an error. Please retry."
    return "Something went wrong handling that request. Please retry."


# ---- agent path: POST /chat ----


def _stream_chat(req: ChatRequest):
    """Generator yielding SSE events from the Anthropic tool runner.

    The 12 @beta_tool functions are built *inside* this request scope so
    they close over a per-request `recorded` list — module-scope tools
    would bleed tool results across concurrent requests.

    Why explicit functions instead of a shared decorator: @beta_tool
    derives each tool's JSON schema from the function signature. A
    `**kwargs` wrapper erases that signature and the model then guesses
    argument names. Each tool below therefore keeps its real typed
    signature and calls `_capture` in its own body.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        yield _sse({"type": "error", "message": "ANTHROPIC_API_KEY not configured on the server"})
        return

    # Per-request capture of every tool call's structured result.
    recorded: list[dict] = []

    def _capture(name: str, args: dict, out: str) -> str:
        """Parse a tool's JSON-string output and record (name, args, result)."""
        try:
            parsed = json.loads(out)
        except (json.JSONDecodeError, TypeError):
            parsed = {"raw": str(out)}
        recorded.append({"name": name, "args": args, "result": parsed})
        return out

    @beta_tool
    def search_corpus(query: str, tier: str | None = None,
                      congress: int | None = None, limit: int = 5) -> str:
        """Search the corpus by free-text query; returns ranked lightweight hits."""
        return _capture(
            "search_corpus",
            {"query": query, "tier": tier, "congress": congress, "limit": limit},
            tool_search_corpus(query, tier=tier, congress=congress, limit=limit),
        )

    @beta_tool
    def get_bill(bill_id: str) -> str:
        """Get a bill's metadata and top-level section table of contents."""
        return _capture("get_bill", {"bill_id": bill_id}, tool_get_bill(bill_id))

    @beta_tool
    def get_section(section_id: str, as_of: str | None = None) -> str:
        """Get a section's verbatim text plus its canonical_citation."""
        return _capture(
            "get_section", {"section_id": section_id, "as_of": as_of},
            tool_get_section(section_id, as_of=as_of),
        )

    @beta_tool
    def resolve_citation(citation_string: str) -> str:
        """Parse a free-text legislative citation into canonical section IDs."""
        return _capture(
            "resolve_citation", {"citation_string": citation_string},
            tool_resolve_citation(citation_string),
        )

    @beta_tool
    def corpus_coverage() -> str:
        """Report what is and isn't in the corpus — call when asked about scope."""
        return _capture("corpus_coverage", {}, tool_corpus_coverage())

    @beta_tool
    def get_citation_graph(section_id: str, direction: str = "both",
                           max_nodes: int = 25) -> str:
        """Typed citation graph around a section (depth=1)."""
        return _capture(
            "get_citation_graph",
            {"section_id": section_id, "direction": direction, "max_nodes": max_nodes},
            tool_get_citation_graph(section_id, direction=direction, max_nodes=max_nodes),
        )

    @beta_tool
    def get_defined_terms(bill_id: str) -> str:
        """Get every term a bill formally defines."""
        return _capture(
            "get_defined_terms", {"bill_id": bill_id},
            tool_get_defined_terms(bill_id),
        )

    @beta_tool
    def get_amendments(bill_id: str) -> str:
        """Get every amendment a bill makes to existing U.S. Code."""
        return _capture(
            "get_amendments", {"bill_id": bill_id}, tool_get_amendments(bill_id),
        )

    @beta_tool
    def get_amendments_targeting(statute_section_id: str) -> str:
        """Get every amendment in the corpus targeting a U.S. Code section."""
        return _capture(
            "get_amendments_targeting", {"statute_section_id": statute_section_id},
            tool_get_amendments_targeting(statute_section_id),
        )

    @beta_tool
    def find_bills_defining(term: str, definition_type: str | None = None,
                            by_reference_to: str | None = None,
                            also_match: list[str] | None = None) -> str:
        """AGGREGATE: every bill defining a term, in one call. Prefer over search+loop."""
        return _capture(
            "find_bills_defining",
            {"term": term, "definition_type": definition_type,
             "by_reference_to": by_reference_to, "also_match": also_match},
            tool_find_bills_defining(term, definition_type=definition_type,
                                     by_reference_to=by_reference_to, also_match=also_match),
        )

    @beta_tool
    def find_bills_amending(statute_section_id: str) -> str:
        """AGGREGATE: per-bill rollup of bills amending a U.S. Code section."""
        return _capture(
            "find_bills_amending", {"statute_section_id": statute_section_id},
            tool_find_bills_amending(statute_section_id),
        )

    @beta_tool
    def find_definitions_of(term: str) -> str:
        """AGGREGATE: every bill's verbatim definition of a term, side by side."""
        return _capture(
            "find_definitions_of", {"term": term}, tool_find_definitions_of(term),
        )

    tools = [
        search_corpus, get_bill, get_section, resolve_citation, corpus_coverage,
        get_citation_graph, get_defined_terms, get_amendments,
        get_amendments_targeting, find_bills_defining, find_bills_amending,
        find_definitions_of,
    ]

    client = anthropic.Anthropic()
    request_messages = _to_anthropic_history(req.history) + [
        {"role": "user", "content": req.message}
    ]

    try:
        runner = client.beta.messages.tool_runner(
            model="claude-opus-4-7",
            max_tokens=8192,
            tools=tools,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=request_messages,
        )

        emitted = 0
        for msg in runner:
            for block in msg.content:
                if block.type == "text" and block.text:
                    yield _sse({"type": "text", "delta": block.text})
                elif block.type == "tool_use":
                    yield _sse({
                        "type": "tool_call",
                        "name": block.name,
                        "args": block.input or {},
                    })
            # The SDK executes tools between yielded messages, so by the
            # time the next message arrives the prior message's tool
            # calls have run and appended to `recorded`. Drain whatever
            # is new and emit one tool_result event per entry.
            while emitted < len(recorded):
                yield _sse({"type": "tool_result", **recorded[emitted]})
                emitted += 1
        # Final drain in case the last message's tools recorded late.
        while emitted < len(recorded):
            yield _sse({"type": "tool_result", **recorded[emitted]})
            emitted += 1
        yield _sse({"type": "done"})
    except anthropic.APIError as e:
        print(f"[/chat] API error: {type(e).__name__}: {e}", file=sys.stderr)
        yield _sse({"type": "error", "message": _friendly_error(e)})
    except Exception as e:
        print(f"[/chat] unexpected error: {type(e).__name__}: {e}", file=sys.stderr)
        yield _sse({"type": "error", "message": _friendly_error(e)})


@app.post("/chat")
def chat(req: ChatRequest):
    """Stream a chat response as SSE."""
    return StreamingResponse(
        _stream_chat(req),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disables proxy buffering (e.g., behind nginx)
        },
    )


# ---- REST path: GET /api/* (read-only, deterministic, no agent turn) ----
#
# Each route wraps a tool_* function and returns json.loads() of its
# output — the same trick /coverage uses. Frontend navigation (clicking
# between bills) hits these instead of /chat: instant, free, no tokens.


def _parsed(out: str) -> Any:
    """json.loads a tool's string output; never raises into the route."""
    try:
        return json.loads(out)
    except (json.JSONDecodeError, TypeError):
        return {"error": "tool returned non-JSON output", "raw": str(out)}


@app.get("/api/search")
def api_search(query: str, tier: str | None = None,
               congress: int | None = None, limit: int = 5) -> Any:
    """Free-text corpus search — ranked lightweight bill hits."""
    return _parsed(tool_search_corpus(query, tier=tier, congress=congress, limit=limit))


@app.get("/api/bill/{bill_id}")
def api_bill(bill_id: str) -> Any:
    """Bill metadata + top-level section table of contents."""
    return _parsed(tool_get_bill(bill_id))


@functools.lru_cache(maxsize=256)
def _full_section_tree(bill_id: str) -> str:
    """Recursively assemble a bill's full nested section tree.

    get_bill returns only top-level sections; the Decomp structure
    outline and the Text panel need the whole tree. Cached because bill
    text is immutable in v1. Returns a JSON string so lru_cache stores a
    hashable value.
    """
    bill = json.loads(tool_get_bill(bill_id))
    if bill.get("error") or bill.get("not_found"):
        return json.dumps(bill)

    def _node(section_id: str) -> dict:
        sec = json.loads(tool_get_section(section_id))
        children = sec.get("child_section_ids") or []
        return {
            "section_id": sec.get("section_id"),
            "heading": sec.get("heading"),
            "canonical_citation": sec.get("canonical_citation"),
            "text": sec.get("text"),
            "children": [_node(c) for c in children],
        }

    tree = {
        "bill_id": bill_id,
        "sections": [_node(s["section_id"]) for s in bill.get("sections", [])],
    }
    return json.dumps(tree)


@app.get("/api/bill/{bill_id}/sections")
def api_bill_sections(bill_id: str) -> Any:
    """Full nested section tree for a bill (heading, citation, verbatim text)."""
    return json.loads(_full_section_tree(bill_id))


@app.get("/api/bill/{bill_id}/defined_terms")
def api_bill_defined_terms(bill_id: str) -> Any:
    """Every term a bill formally defines."""
    return _parsed(tool_get_defined_terms(bill_id))


@app.get("/api/bill/{bill_id}/amendments")
def api_bill_amendments(bill_id: str) -> Any:
    """Every amendment a bill makes to existing U.S. Code."""
    return _parsed(tool_get_amendments(bill_id))


@app.get("/api/section")
def api_section(section_id: str, as_of: str | None = None) -> Any:
    """A section's verbatim text + canonical citation. section_id is a query
    param because section IDs contain '::'."""
    return _parsed(tool_get_section(section_id, as_of=as_of))


@app.get("/api/citation_graph")
def api_citation_graph(section_id: str, direction: str = "both",
                       max_nodes: int = 25) -> Any:
    """Typed citation graph around a section (depth=1)."""
    return _parsed(tool_get_citation_graph(section_id, direction=direction, max_nodes=max_nodes))


@app.get("/api/resolve")
def api_resolve(citation_string: str) -> Any:
    """Parse a free-text legislative citation into canonical section IDs."""
    return _parsed(tool_resolve_citation(citation_string))


@app.get("/api/coverage")
def api_coverage() -> Any:
    """Corpus coverage snapshot — what's in scope, what's not, totals."""
    return _parsed(tool_corpus_coverage())


# ---- legacy aliases + test page ----


@app.get("/coverage")
def coverage() -> dict:
    """Alias of /api/coverage (kept for the existing test page)."""
    return json.loads(tool_corpus_coverage())


@app.get("/health")
def health() -> dict:
    db = Path(os.environ.get("POLILABS_DB", "data/polilabs.db"))
    return {
        "ok": db.exists() and bool(os.environ.get("ANTHROPIC_API_KEY")),
        "db_present": db.exists(),
        "anthropic_key_configured": bool(os.environ.get("ANTHROPIC_API_KEY")),
    }


@app.get("/")
def index():
    """Serve the bare-bones test page so the backend is usable without a frontend."""
    page = Path(__file__).resolve().parent / "static" / "index.html"
    if not page.exists():
        raise HTTPException(404, "static/index.html missing")
    return FileResponse(page)


def main():
    db = Path(os.environ.get("POLILABS_DB", "data/polilabs.db"))
    if not db.exists():
        print(f"[error] polilabs.db not found at {db}", file=sys.stderr)
        print("        Build it first: python scripts/build_index.py", file=sys.stderr)
        sys.exit(1)
    port = int(os.environ.get("POLILABS_PORT", "8000"))
    print(f"[polilabs] listening on http://localhost:{port}")
    print(f"[polilabs] test page at http://localhost:{port}/")
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
