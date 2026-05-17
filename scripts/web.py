"""Gradio web UI — same agent as scripts/chat.py, accessible via a browser.

Launches a local site at http://localhost:7860 with a chat interface backed
by Claude Opus 4.7 and the six polilabs API primitives.

Run:
    python scripts/web.py
    # Add --share to expose a public *.gradio.live tunnel (proceed with caution —
    # exposes your Anthropic-billed quota to anyone with the link).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import anthropic
import gradio as gr
from anthropic import beta_tool

from agent.tools import (
    SYSTEM_PROMPT,
    tool_corpus_coverage,
    tool_get_bill,
    tool_get_section,
    tool_resolve_citation,
    tool_search_corpus,
)


# ---- @beta_tool wrappers (signatures drive schema generation) ----


@beta_tool
def search_corpus(
    query: str,
    tier: str | None = None,
    congress: int | None = None,
    limit: int = 5,
) -> str:
    """Search the polilabs AI-governance corpus by free-text query. Returns
    ranked lightweight hits — never full bill text.

    Args:
        query: Free-text query.
        tier: Optional 'A' or 'B' filter.
        congress: Optional 118 or 119 filter.
        limit: Max hits (1-25, default 5).
    """
    return tool_search_corpus(query, tier=tier, congress=congress, limit=limit)


@beta_tool
def get_bill(bill_id: str) -> str:
    """Get a bill's metadata and section table of contents — no body text.

    Args:
        bill_id: e.g. '118-hr-5949'.
    """
    return tool_get_bill(bill_id)


@beta_tool
def get_section(section_id: str, as_of: str | None = None) -> str:
    """Get a section's verbatim text plus its canonical_citation. Always
    quote canonical_citation when citing the section.

    Args:
        section_id: from a bill's section list.
        as_of: optional ISO date for point-in-time queries.
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
    """Report what is and isn't in the corpus — use this to give honest
    scope answers instead of bluffing on out-of-scope queries.
    """
    return tool_corpus_coverage()


TOOLS = [search_corpus, get_bill, get_section, resolve_citation, corpus_coverage]


def _format_tool_call(name: str, args: dict) -> str:
    """Render a tool call as a one-line italic note to interleave in the response."""
    args_str = ", ".join(f"{k}={v!r}" for k, v in (args or {}).items())
    if len(args_str) > 120:
        args_str = args_str[:117] + "..."
    return f"\n\n_→ {name}({args_str})_\n\n"


def _to_anthropic_history(messages: list) -> list:
    """Convert Gradio's messages-format history into the Anthropic shape.

    Gradio (type='messages') uses [{'role': ..., 'content': str}, ...]. We
    drop the assistant messages because tool_use/tool_result blocks must
    travel together with their matching pairs to be valid, and the UI
    history only stores final-rendered text. Keeping just user turns gives
    Claude the conversational context without breaking tool-use validity.
    """
    out = []
    for m in messages:
        if m["role"] == "user":
            out.append({"role": "user", "content": m["content"]})
    return out


def respond(message: str, history: list):
    """Streaming generator yielding partial response strings to Gradio."""
    client = anthropic.Anthropic()

    prior = _to_anthropic_history(history)
    request_messages = prior + [{"role": "user", "content": message}]

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

        accumulated = ""
        for msg in runner:
            for block in msg.content:
                if block.type == "text" and block.text:
                    accumulated += block.text
                    yield accumulated
                elif block.type == "tool_use":
                    accumulated += _format_tool_call(block.name, block.input or {})
                    yield accumulated
    except anthropic.APIError as e:
        yield f"**API error:** `{type(e).__name__}: {e}`"
    except Exception as e:
        yield f"**Error:** `{type(e).__name__}: {e}`"


EXAMPLES = [
    "What bills in the 119th Congress address frontier model safety?",
    "What does Sec. 3(a)(1) of H.R. 1736, 119th Cong. actually require?",
    "Are there bills about facial recognition in federal contracting?",
    "What's NOT in this corpus?",
    "Find AI bills from Sen. Hawley.",
]


DESCRIPTION = """\
A queryable, citation-accurate database of US federal AI-governance legislation —
**191 bills** from the **118th and 119th Congress** (2023–present).

Powered by Claude Opus 4.7 with five tools: `search_corpus`, `get_bill`,
`get_section`, `resolve_citation`, `corpus_coverage`. Every citation is quoted
verbatim from the corpus; nothing is reconstructed from memory.

_Out of v1 scope: regulatory actions (FTC, NIST, Commerce) and executive orders._"""


def _check_setup() -> None:
    db = Path(os.environ.get("POLILABS_DB", "data/polilabs.db"))
    if not db.exists():
        print(f"[error] polilabs.db not found at {db}", file=sys.stderr)
        print("        Build it first: python scripts/build_index.py", file=sys.stderr)
        sys.exit(1)
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("[error] ANTHROPIC_API_KEY not set in .env", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--share", action="store_true",
                    help="Expose a public *.gradio.live tunnel. Default is localhost-only.")
    ap.add_argument("--port", type=int, default=7860, help="Local port (default 7860).")
    args = ap.parse_args()

    _check_setup()

    demo = gr.ChatInterface(
        fn=respond,
        title="polilabs",
        description=DESCRIPTION,
        examples=EXAMPLES,
        cache_examples=False,
        chatbot=gr.Chatbot(height=540, label="Conversation"),
        textbox=gr.Textbox(placeholder="Ask about an AI-governance bill...", autofocus=True),
        analytics_enabled=False,
    )

    demo.launch(server_port=args.port, share=args.share, inbrowser=not args.share)


if __name__ == "__main__":
    main()
