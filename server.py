"""FastAPI backend — the 12-tool polilabs agent, exposed over HTTP.

Two access paths for a frontend:

  1. Agent path — POST /chat (SSE). Answers a question; streams the
     answer text, the tool calls the agent made, and the structured
     tool *results* (so the UI can render decomposition panels).
  2. REST path — GET /api/*. Deterministic, read-only data fetches with
     no agent turn (no token cost, no latency) — used when the user
     clicks/navigates between bills.

POST /chat SSE event types: text, tool_call, tool_result, done, error.

Auth: per-user accounts (see auth/). POST /auth/signup and /auth/login
are public and return a JWT; /chat and every /api/* route below require
an `Authorization: Bearer <token>` header. /health, /coverage and the
test page at / stay open.

REST endpoints (all read-only, JSON; all login-only):
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

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent))
load_dotenv(Path(__file__).resolve().parent / ".env")

import anthropic
import uvicorn
from anthropic import beta_tool
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from auth import init_db, require_user
from auth import router as auth_router
from auth import usage
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

# ---- auth ----
#
# Per-user accounts (SQLite + bcrypt + JWT). The /auth/* routes are
# public; the agent path (/chat) and the /api/* REST surface are gated
# behind `require_user` further down. init_db() creates the users table
# on first boot — idempotent.
init_db()
app.include_router(auth_router)


class ChatMessageIn(BaseModel):
    role: str = Field(description="'user' or 'assistant'")
    content: str


class ChatRequest(BaseModel):
    message: str = Field(description="The new user message")
    history: list[ChatMessageIn] = Field(default_factory=list, description="Prior turns (user/assistant text only)")


def _to_anthropic_history(history: list[ChatMessageIn]) -> list[dict]:
    """Replay the conversation so far. The frontend sends each prior turn
    as a user question + a plain-text assistant answer (no tool_use
    blocks), so both roles replay to the API cleanly — and a follow-up
    question keeps the context of earlier turns.
    """
    return [{"role": m.role, "content": m.content} for m in history
            if m.role in ("user", "assistant") and (m.content or "").strip()]


def _sse(event: dict[str, Any]) -> str:
    """Format one Server-Sent Event line."""
    return f"data: {json.dumps(event, default=str)}\n\n"


# ---- latency instrumentation ----
#
# A /chat turn is an agentic loop: the model is called, it may call
# tools, then it is called again, until it produces a final answer.
# Wall-clock latency therefore splits into (a) LLM round-trips and
# (b) tool execution (SQLite FTS5 + Kùzu graph). This block measures
# that split per turn so we can see which one dominates, rather than
# guessing. One JSONL row per turn lands in data/traces/<date>.jsonl;
# a one-line summary also goes to stderr. Read-only — it changes no
# tool result and no SSE payload shape.

_TRACE_DIR = Path(__file__).resolve().parent / "data" / "traces"


def _usage_of(msg: Any) -> dict[str, Any]:
    """Extract token usage from one runner message (defensively)."""
    u = getattr(msg, "usage", None)
    if u is None:
        return {}
    return {
        "input": getattr(u, "input_tokens", None),
        "output": getattr(u, "output_tokens", None),
        "cache_read": getattr(u, "cache_read_input_tokens", None),
        "cache_creation": getattr(u, "cache_creation_input_tokens", None),
    }


def _write_trace(
    req: "ChatRequest",
    t_start: float,
    iterations: list[dict],
    tool_timings: list[dict],
    error: str | None = None,
    first_token_ms: float | None = None,
) -> None:
    """Append one turn's latency trace to data/traces/<date>.jsonl and
    log a one-line summary to stderr. Never raises — instrumentation
    must not break a turn.

    `first_token_ms` is time-to-first-token: wall time from request
    start to the first text delta the user sees. With streaming this
    is the latency that actually matters for perceived speed."""
    total_ms = (time.perf_counter() - t_start) * 1000.0
    llm_ms = sum(it["llm_ms"] for it in iterations)
    tool_ms = sum(t["ms"] for t in tool_timings)
    trace = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "message_chars": len(req.message or ""),
        "history_turns": len(req.history),
        "total_ms": round(total_ms, 1),
        "first_token_ms": round(first_token_ms, 1) if first_token_ms is not None else None,
        "n_iterations": len(iterations),
        "n_tool_calls": len(tool_timings),
        "llm_ms_total": round(llm_ms, 1),
        "tool_ms_total": round(tool_ms, 1),
        "iterations": iterations,
        "tool_calls": tool_timings,
    }
    if error:
        trace["error"] = error
    ttft = f"{first_token_ms:.0f}ms" if first_token_ms is not None else "n/a"
    print(
        f"[/chat trace] total={total_ms:.0f}ms ttft={ttft} "
        f"llm={llm_ms:.0f}ms tools={tool_ms:.0f}ms "
        f"iterations={len(iterations)} tool_calls={len(tool_timings)}"
        + (f" error={error}" if error else ""),
        file=sys.stderr,
    )
    try:
        _TRACE_DIR.mkdir(parents=True, exist_ok=True)
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with open(_TRACE_DIR / f"{day}.jsonl", "a") as f:
            f.write(json.dumps(trace, default=str) + "\n")
    except OSError as e:
        print(f"[/chat trace] could not write trace file: {e}", file=sys.stderr)


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


def _stream_chat(req: ChatRequest, user: dict):
    """Generator yielding SSE events from the Anthropic tool runner.

    The 12 @beta_tool functions are built *inside* this request scope so
    they close over a per-request `recorded` list — module-scope tools
    would bleed tool results across concurrent requests.

    Why explicit functions instead of a shared decorator: @beta_tool
    derives each tool's JSON schema from the function signature. A
    `**kwargs` wrapper erases that signature and the model then guesses
    argument names. Each tool below therefore keeps its real typed
    signature and calls `_run_tool` in its own body.

    `user` is the authenticated user dict from require_user. Used by
    auth.usage for per-account token accounting; pre-call refusal and
    mid-stream abort happen below.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        yield _sse({"type": "error", "message": "ANTHROPIC_API_KEY not configured on the server"})
        return

    # Pre-call rate-limit gate. Cheap (one indexed SQLite read); failure
    # mode is a single SSE error event + done, no Anthropic call made.
    # The exact wording — "Error: usage limit reached for {email}" —
    # is fixed by auth.usage.limit_error_message so the wording can't
    # drift between pre-call and mid-stream paths.
    if usage.is_over_limit(user["id"], user.get("email")):
        yield _sse({"type": "error", "message": usage.limit_error_message(user["email"])})
        yield _sse({"type": "done"})
        return

    # Per-request capture of every tool call's structured result.
    recorded: list[dict] = []
    # Parallel per-tool wall-clock timings, kept separate from `recorded`
    # so the tool_result SSE payload shape stays byte-identical.
    tool_timings: list[dict] = []

    def _run_tool(name: str, args: dict, fn: Any) -> str:
        """Execute a tool callable, time it, and record its result plus
        its wall-clock duration. `fn` is a zero-arg callable so the timer
        brackets only the real tool work."""
        t = time.perf_counter()
        out = fn()
        elapsed_ms = (time.perf_counter() - t) * 1000.0
        try:
            parsed = json.loads(out)
        except (json.JSONDecodeError, TypeError):
            parsed = {"raw": str(out)}
        recorded.append({"name": name, "args": args, "result": parsed})
        tool_timings.append({"name": name, "ms": round(elapsed_ms, 1)})
        return out

    @beta_tool
    def search_corpus(query: str, topic: str = "ai_governance",
                      tier: str | None = None,
                      congress: int | None = None, limit: int = 5) -> str:
        """Search a topic-scoped corpus by free-text query (BM25 + dense
        embeddings via RRF). `topic` must be either "ai_governance" (the
        191-bill AI corpus, default) or "redistricting" (the federal
        voting-rights / redistricting seed corpus). Returns ranked
        lightweight hits with provenance.
        """
        return _run_tool(
            "search_corpus",
            {"query": query, "topic": topic, "tier": tier, "congress": congress, "limit": limit},
            lambda: tool_search_corpus(query, topic=topic, tier=tier, congress=congress, limit=limit),
        )

    @beta_tool
    def get_bill(bill_id: str) -> str:
        """Get a bill's metadata and top-level section table of contents."""
        return _run_tool("get_bill", {"bill_id": bill_id}, lambda: tool_get_bill(bill_id))

    @beta_tool
    def get_section(section_id: str, as_of: str | None = None) -> str:
        """Get a section's verbatim text plus its canonical_citation."""
        return _run_tool(
            "get_section", {"section_id": section_id, "as_of": as_of},
            lambda: tool_get_section(section_id, as_of=as_of),
        )

    @beta_tool
    def resolve_citation(citation_string: str) -> str:
        """Parse a free-text legislative citation into canonical section IDs."""
        return _run_tool(
            "resolve_citation", {"citation_string": citation_string},
            lambda: tool_resolve_citation(citation_string),
        )

    @beta_tool
    def corpus_coverage() -> str:
        """Report what is and isn't in the corpus — call when asked about scope."""
        return _run_tool("corpus_coverage", {}, lambda: tool_corpus_coverage())

    @beta_tool
    def get_citation_graph(section_id: str, direction: str = "both",
                           max_nodes: int = 25) -> str:
        """Typed citation graph around a section (depth=1)."""
        return _run_tool(
            "get_citation_graph",
            {"section_id": section_id, "direction": direction, "max_nodes": max_nodes},
            lambda: tool_get_citation_graph(section_id, direction=direction, max_nodes=max_nodes),
        )

    @beta_tool
    def get_defined_terms(bill_id: str) -> str:
        """Get every term a bill formally defines."""
        return _run_tool(
            "get_defined_terms", {"bill_id": bill_id},
            lambda: tool_get_defined_terms(bill_id),
        )

    @beta_tool
    def get_amendments(bill_id: str) -> str:
        """Get every amendment a bill makes to existing U.S. Code."""
        return _run_tool(
            "get_amendments", {"bill_id": bill_id}, lambda: tool_get_amendments(bill_id),
        )

    @beta_tool
    def get_amendments_targeting(statute_section_id: str) -> str:
        """Get every amendment in the corpus targeting a U.S. Code section."""
        return _run_tool(
            "get_amendments_targeting", {"statute_section_id": statute_section_id},
            lambda: tool_get_amendments_targeting(statute_section_id),
        )

    @beta_tool
    def find_bills_defining(term: str, definition_type: str | None = None,
                            by_reference_to: str | None = None,
                            also_match: list[str] | None = None) -> str:
        """AGGREGATE: every bill defining a term, in one call. Prefer over search+loop."""
        return _run_tool(
            "find_bills_defining",
            {"term": term, "definition_type": definition_type,
             "by_reference_to": by_reference_to, "also_match": also_match},
            lambda: tool_find_bills_defining(term, definition_type=definition_type,
                                             by_reference_to=by_reference_to,
                                             also_match=also_match),
        )

    @beta_tool
    def find_bills_amending(statute_section_id: str) -> str:
        """AGGREGATE: per-bill rollup of bills amending a U.S. Code section."""
        return _run_tool(
            "find_bills_amending", {"statute_section_id": statute_section_id},
            lambda: tool_find_bills_amending(statute_section_id),
        )

    @beta_tool
    def find_definitions_of(term: str) -> str:
        """AGGREGATE: every bill's verbatim definition of a term, side by side."""
        return _run_tool(
            "find_definitions_of", {"term": term}, lambda: tool_find_definitions_of(term),
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

    # Latency instrumentation: t_start brackets the whole turn;
    # `iterations` accumulates one record per runner step; first_token_ms
    # is set when the first text delta reaches the user.
    t_start = time.perf_counter()
    iterations: list[dict] = []
    first_token_ms: float | None = None

    try:
        # stream=True returns a BetaStreamingToolRunner: iterating it
        # yields one message stream per LLM call, and each stream yields
        # token-level events. Tools still execute automatically between
        # streams. This drops time-to-first-token from a whole-answer
        # wait to roughly first-token latency.
        runner = client.beta.messages.tool_runner(
            # Env override lets the eval harness swap to opus-4-7 without
            # touching the prod default. Set POLILABS_MODEL to any
            # Anthropic model ID.
            model=os.environ.get("POLILABS_MODEL", "claude-sonnet-4-6"),
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
            stream=True,
        )

        emitted = 0
        last_t = t_start
        tools_seen = 0
        for stream in runner:
            # Consume token-level events: text_delta events stream
            # straight to the user (this is the fine-grained path the
            # SDK's own text_stream uses); a tool_use block is announced
            # once its content block closes and its input is assembled.
            for event in stream:
                if (event.type == "content_block_delta"
                        and event.delta.type == "text_delta"
                        and event.delta.text):
                    if first_token_ms is None:
                        first_token_ms = (time.perf_counter() - t_start) * 1000.0
                    yield _sse({"type": "text", "delta": event.delta.text})
                elif event.type == "content_block_stop":
                    block = getattr(event, "content_block", None)
                    if block is not None and getattr(block, "type", None) == "tool_use":
                        yield _sse({
                            "type": "tool_call",
                            "name": block.name,
                            "args": block.input or {},
                        })
            now = time.perf_counter()
            final_msg = stream.get_final_message()
            # The SDK executes tools between streams, so by the time the
            # next stream starts the prior step's tool calls have run and
            # appended to `recorded`. Drain whatever is new.
            while emitted < len(recorded):
                yield _sse({"type": "tool_result", **recorded[emitted]})
                emitted += 1
            # Attribute this step's wall time: the gap is one LLM call
            # plus any tools that ran in the window before it. llm_ms is
            # the remainder.
            gap_ms = (now - last_t) * 1000.0
            window_tools = tool_timings[tools_seen:]
            tool_ms = sum(t["ms"] for t in window_tools)
            iter_usage = _usage_of(final_msg)
            iterations.append({
                "i": len(iterations) + 1,
                "gap_ms": round(gap_ms, 1),
                "tool_ms": round(tool_ms, 1),
                "llm_ms": round(max(gap_ms - tool_ms, 0.0), 1),
                "tools": [t["name"] for t in window_tools],
                "usage": iter_usage,
            })
            last_t = now
            tools_seen = len(tool_timings)
            # Per-iteration usage accumulation + mid-stream abort. Exempt
            # accounts skip both the DB write and the check. The current
            # iteration's tokens are already spent at the Anthropic API
            # by the time we see them — we charge them, then refuse the
            # NEXT iteration if it would exceed the cap. The user sees
            # whatever this iteration produced followed by the cap error.
            if not usage.is_exempt(user.get("email")):
                usage.add_usage(
                    user["id"],
                    iter_usage.get("input") or 0,
                    iter_usage.get("output") or 0,
                )
                if usage.is_over_limit(user["id"], user.get("email")):
                    yield _sse({
                        "type": "error",
                        "message": usage.limit_error_message(user["email"]),
                    })
                    break
        # Final drain in case the last step's tools recorded late.
        while emitted < len(recorded):
            yield _sse({"type": "tool_result", **recorded[emitted]})
            emitted += 1
        _write_trace(req, t_start, iterations, tool_timings,
                     first_token_ms=first_token_ms)
        yield _sse({"type": "done"})
    except anthropic.APIError as e:
        print(f"[/chat] API error: {type(e).__name__}: {e}", file=sys.stderr)
        _write_trace(req, t_start, iterations, tool_timings,
                     error=type(e).__name__, first_token_ms=first_token_ms)
        yield _sse({"type": "error", "message": _friendly_error(e)})
    except Exception as e:
        print(f"[/chat] unexpected error: {type(e).__name__}: {e}", file=sys.stderr)
        _write_trace(req, t_start, iterations, tool_timings,
                     error=type(e).__name__, first_token_ms=first_token_ms)
        yield _sse({"type": "error", "message": _friendly_error(e)})


@app.post("/chat")
def chat(req: ChatRequest, _user: dict = Depends(require_user)):
    """Stream a chat response as SSE. Login-only — each turn spends
    Anthropic tokens, so an anonymous caller must not reach it. The
    user dict is threaded through so auth.usage can charge tokens to
    the right account and refuse calls past the per-account cap."""
    return StreamingResponse(
        _stream_chat(req, _user),
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
#
# Every /api/* route is login-only (`Depends(require_user)`): the web
# app requires an account, so the data surface it reads requires one too.


def _parsed(out: str) -> Any:
    """json.loads a tool's string output; never raises into the route."""
    try:
        return json.loads(out)
    except (json.JSONDecodeError, TypeError):
        return {"error": "tool returned non-JSON output", "raw": str(out)}


@app.get("/api/search")
def api_search(query: str, topic: str = "ai_governance",
               tier: str | None = None,
               congress: int | None = None, limit: int = 5,
               _user: dict = Depends(require_user)) -> Any:
    """Free-text corpus search — ranked lightweight bill hits. `topic`
    selects the corpus (default `ai_governance`); frontends that don't
    pass it get the legacy AI behavior."""
    return _parsed(tool_search_corpus(query, topic=topic, tier=tier, congress=congress, limit=limit))


@app.get("/api/bill/{bill_id}")
def api_bill(bill_id: str, _user: dict = Depends(require_user)) -> Any:
    """Bill metadata + top-level section table of contents."""
    return _parsed(tool_get_bill(bill_id))


# Successful section trees only — bill text is immutable in v1, so a
# built tree is safe to keep. Error / not_found results are deliberately
# NOT cached: a transient backend hiccup (e.g. the embedded graph DB
# under load) must never get frozen in and leave a bill permanently blank.
_section_tree_cache: dict[str, str] = {}


def _full_section_tree(bill_id: str) -> str:
    """Recursively assemble a bill's full nested section tree.

    get_bill returns only top-level sections; the Decomp outline and the
    Text panel need the whole tree, and each node needs its OWN verbatim
    text — the chapeau for an internal node, the full body for a leaf.
    The stored `text` is text_full (a node's text plus every
    descendant's), so own-text = text_full minus each child's rendered
    segment (its marker + heading + text_full). Returns a JSON string;
    only successful trees are cached.
    """
    cached = _section_tree_cache.get(bill_id)
    if cached is not None:
        return cached

    bill = json.loads(tool_get_bill(bill_id))
    if bill.get("error") or bill.get("not_found"):
        return json.dumps(bill)  # not cached — keep transient errors retryable

    def _marker_tokens(citation: str) -> list:
        """In-text marker forms a subsection may appear as, derived from
        its canonical citation — 'Sec. I(101)' -> ['(101)', '101.', '101)']."""
        groups = re.findall(r"\(([0-9A-Za-z]+)\)", citation or "")
        if not groups:
            m = re.search(r"(?:Sec\.|§)\s*([0-9A-Za-z]+)", citation or "")
            groups = [m.group(1)] if m else []
        if not groups:
            return []
        tok = groups[-1]
        return ["(" + tok + ")", tok + ".", tok + ")"]

    def _own_text(full: str, children: list) -> str:
        """A node's own text: its text_full with each child's rendered
        segment (marker + heading + body) removed."""
        t = full or ""
        for c in children:
            cf = c.get("_full") or ""
            if not cf:
                continue
            i = t.find(cf)
            if i < 0:
                continue
            start, end = i, i + len(cf)
            before = t[:start]
            heading = (c.get("heading") or "").strip()
            if heading:
                hi = before.rfind(heading)
                if hi >= 0 and before[hi + len(heading):].strip() == "":
                    start = hi
                    before = t[:start]
            for tok in _marker_tokens(c.get("canonical_citation") or ""):
                bs = before.rstrip()
                if bs.endswith(tok):
                    start = len(bs) - len(tok)
                    break
            t = t[:start] + t[end:]
        return t.strip()

    def _build(section_id: str) -> dict:
        sec = json.loads(tool_get_section(section_id))
        children = [_build(c) for c in (sec.get("child_section_ids") or [])]
        full = sec.get("text") or ""
        return {
            "section_id": sec.get("section_id"),
            "heading": sec.get("heading"),
            "canonical_citation": sec.get("canonical_citation"),
            "text": _own_text(full, children),
            "children": children,
            "_full": full,          # internal — stripped before the tree is sent
        }

    def _strip(node: dict) -> dict:
        node.pop("_full", None)
        for c in node["children"]:
            _strip(c)
        return node

    tree = {
        "bill_id": bill_id,
        "sections": [_strip(_build(s["section_id"])) for s in bill.get("sections", [])],
    }
    result = json.dumps(tree)
    _section_tree_cache[bill_id] = result
    return result


@app.get("/api/bill/{bill_id}/sections")
def api_bill_sections(bill_id: str, _user: dict = Depends(require_user)) -> Any:
    """Full nested section tree for a bill (heading, citation, verbatim text)."""
    return json.loads(_full_section_tree(bill_id))


@app.get("/api/bill/{bill_id}/defined_terms")
def api_bill_defined_terms(bill_id: str, _user: dict = Depends(require_user)) -> Any:
    """Every term a bill formally defines."""
    return _parsed(tool_get_defined_terms(bill_id))


@app.get("/api/bill/{bill_id}/amendments")
def api_bill_amendments(bill_id: str, _user: dict = Depends(require_user)) -> Any:
    """Every amendment a bill makes to existing U.S. Code."""
    return _parsed(tool_get_amendments(bill_id))


@app.get("/api/section")
def api_section(section_id: str, as_of: str | None = None,
                _user: dict = Depends(require_user)) -> Any:
    """A section's verbatim text + canonical citation. section_id is a query
    param because section IDs contain '::'."""
    return _parsed(tool_get_section(section_id, as_of=as_of))


@app.get("/api/citation_graph")
def api_citation_graph(section_id: str, direction: str = "both",
                       max_nodes: int = 25,
                       _user: dict = Depends(require_user)) -> Any:
    """Typed citation graph around a section (depth=1)."""
    return _parsed(tool_get_citation_graph(section_id, direction=direction, max_nodes=max_nodes))


@app.get("/api/resolve")
def api_resolve(citation_string: str, _user: dict = Depends(require_user)) -> Any:
    """Parse a free-text legislative citation into canonical section IDs."""
    return _parsed(tool_resolve_citation(citation_string))


@app.get("/api/coverage")
def api_coverage(_user: dict = Depends(require_user)) -> Any:
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
