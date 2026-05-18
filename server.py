"""FastAPI backend — same six-tool agent, exposed over HTTP for any frontend.

Endpoints:
  POST /chat          — Server-Sent Events stream. Body: {history, message}.
                        Yields events: {type: 'text', delta: str},
                                       {type: 'tool_call', name: str, args: dict},
                                       {type: 'done'},
                                       {type: 'error', message: str}.
  GET  /coverage      — JSON snapshot of corpus_coverage() (handy for UI footer).
  GET  /health        — Liveness check.
  GET  /              — Bare-bones HTML test page (./static/index.html) that
                        proves the API works end-to-end without any frontend
                        framework.

CORS is open by default so a Lovable-hosted preview or a local Vite dev server
can hit it without configuration. Lock down `allow_origins` before deploying.

Run:
    python server.py
    # or, with uvicorn directly (auto-reload):
    uvicorn server:app --reload --port 8000

Test from terminal:
    curl -N -X POST http://localhost:8000/chat \\
        -H 'Content-Type: application/json' \\
        -d '{"history": [], "message": "What is in this corpus?"}'
"""
from __future__ import annotations

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
    tool_get_bill,
    tool_get_section,
    tool_resolve_citation,
    tool_search_corpus,
)


# ---- agent tools (same signatures as scripts/chat.py and scripts/web.py) ----


@beta_tool
def search_corpus(query: str, tier: str | None = None, congress: int | None = None, limit: int = 5) -> str:
    """Search the corpus by free-text query. Returns ranked lightweight hits.

    Args:
        query: Free-text query.
        tier: Optional 'A' or 'B'.
        congress: Optional 118 or 119.
        limit: Max hits (1-25).
    """
    return tool_search_corpus(query, tier=tier, congress=congress, limit=limit)


@beta_tool
def get_bill(bill_id: str) -> str:
    """Get bill metadata + section ToC. Args: bill_id (e.g. '118-hr-5949')."""
    return tool_get_bill(bill_id)


@beta_tool
def get_section(section_id: str, as_of: str | None = None) -> str:
    """Get a section's verbatim text plus its canonical_citation.

    Args:
        section_id: Section identifier from a bill's section list.
        as_of: Optional ISO date for point-in-time queries.
    """
    return tool_get_section(section_id, as_of=as_of)


@beta_tool
def resolve_citation(citation_string: str) -> str:
    """Parse a free-text legislative citation into canonical section IDs.

    Args:
        citation_string: e.g. 'Sec. 3(a)(1) of H.R. 1736, 119th Cong.'.
    """
    return tool_resolve_citation(citation_string)


@beta_tool
def corpus_coverage() -> str:
    """Report what is and isn't in the corpus — call when asked about scope."""
    return tool_corpus_coverage()


TOOLS = [search_corpus, get_bill, get_section, resolve_citation, corpus_coverage]


# ---- FastAPI app ----


app = FastAPI(
    title="polilabs",
    description="Agent backend for the polilabs AI-governance corpus.",
    version="0.1.0",
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


def _stream_chat(req: ChatRequest):
    """Generator yielding SSE-formatted events from the Anthropic tool runner."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        yield _sse({"type": "error", "message": "ANTHROPIC_API_KEY not configured on the server"})
        return

    client = anthropic.Anthropic()
    request_messages = _to_anthropic_history(req.history) + [
        {"role": "user", "content": req.message}
    ]

    try:
        runner = client.beta.messages.tool_runner(
            model="claude-opus-4-7",
            max_tokens=8192,
            tools=TOOLS,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=request_messages,
        )

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
        yield _sse({"type": "done"})
    except anthropic.APIError as e:
        yield _sse({"type": "error", "message": f"{type(e).__name__}: {e}"})
    except Exception as e:
        yield _sse({"type": "error", "message": f"{type(e).__name__}: {e}"})


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


@app.get("/coverage")
def coverage() -> dict:
    """Return corpus_coverage as JSON — what's in scope, what's not, totals."""
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
