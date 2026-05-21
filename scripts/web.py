"""Gradio web UI — same agent as scripts/chat.py, accessible via a browser.

Launches a local site at http://localhost:7860 with a chat interface backed
by Claude Opus 4.7 and the six polilabs API primitives.

UI design:
  - Tool calls render as collapsed accordions (Gradio ChatMessage metadata)
    so they're visually distinct from the agent's actual response text.
  - Soft theme with slate hues + a custom font and tightened layout.
  - Examples laid out as one-click prompts above the input.

Run:
    python scripts/web.py
    # Add --share to expose a public *.gradio.live tunnel (proceed with
    # caution — exposes your Anthropic-billed quota to anyone with the link).
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


# ---- helpers ----

def _safe_repr(v) -> str:
    """Repr that keeps strings reasonably short."""
    if isinstance(v, str):
        if len(v) > 80:
            return repr(v[:77] + "...")
        return repr(v)
    return repr(v)


def _format_tool_args(args: dict | None) -> str:
    """Render a tool call's args as one compact code line."""
    if not args:
        return "(no arguments)"
    parts = [f"{k}={_safe_repr(v)}" for k, v in args.items()]
    return ", ".join(parts)


def _to_anthropic_history(messages: list) -> list:
    """Convert Gradio's messages-format history into the Anthropic shape.

    The UI history can include assistant messages with metadata (tool call
    accordions), but those are display-only — they don't carry the raw
    tool_use/tool_result block pairs the Anthropic API requires to be
    intact. We drop all assistant messages and re-send user turns only;
    Claude gets conversational context and re-calls tools as needed.
    """
    out = []
    for m in messages:
        if m.get("role") == "user" and isinstance(m.get("content"), str):
            out.append({"role": "user", "content": m["content"]})
    return out


def respond(message: str, history: list):
    """Streaming generator yielding a growing list of assistant ChatMessage dicts.

    For each block from Claude:
      - text blocks extend a single text bubble (or start a new one after a tool call)
      - tool_use blocks emit a separate metadata-tagged bubble that renders
        as a collapsed accordion in Gradio's chat UI
    """
    client = anthropic.Anthropic()

    prior = _to_anthropic_history(history)
    request_messages = prior + [{"role": "user", "content": message}]

    # `messages` is the running list of assistant bubbles for this turn.
    messages: list[dict] = []
    text_bubble_idx: int | None = None  # index of the currently-extending text bubble

    try:
        runner = client.beta.messages.tool_runner(
            model="claude-sonnet-4-6",
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
                    if text_bubble_idx is None:
                        messages.append({"role": "assistant", "content": block.text})
                        text_bubble_idx = len(messages) - 1
                    else:
                        messages[text_bubble_idx]["content"] += block.text
                    yield messages
                elif block.type == "tool_use":
                    args_str = _format_tool_args(block.input)
                    messages.append({
                        "role": "assistant",
                        "content": f"```\n{block.name}({args_str})\n```",
                        "metadata": {
                            "title": f"🔍 Used {block.name}",
                            "status": "done",
                        },
                    })
                    # Subsequent text starts a new bubble below the accordion.
                    text_bubble_idx = None
                    yield messages
    except anthropic.APIError as e:
        yield [{"role": "assistant", "content": f"**API error:** `{type(e).__name__}: {e}`"}]
    except Exception as e:
        yield [{"role": "assistant", "content": f"**Error:** `{type(e).__name__}: {e}`"}]


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

Every citation is quoted verbatim from the corpus; nothing is reconstructed from memory.

_Out of v1 scope: regulatory actions (FTC, NIST, Commerce) and executive orders._"""


THEME = gr.themes.Soft(
    primary_hue="slate",
    secondary_hue="slate",
    neutral_hue="slate",
    text_size=gr.themes.sizes.text_md,
    spacing_size=gr.themes.sizes.spacing_md,
    radius_size=gr.themes.sizes.radius_md,
    font=[
        gr.themes.GoogleFont("Inter"),
        "ui-sans-serif",
        "system-ui",
        "sans-serif",
    ],
    font_mono=[
        gr.themes.GoogleFont("JetBrains Mono"),
        "ui-monospace",
        "monospace",
    ],
).set(
    body_background_fill="#f8fafc",
    background_fill_primary="#ffffff",
    background_fill_secondary="#f1f5f9",
    block_border_width="1px",
    block_border_color="#e2e8f0",
    block_radius="12px",
    block_shadow="0 1px 2px 0 rgb(0 0 0 / 0.04)",
)


CUSTOM_CSS = """
/* Layout — center the chat in a comfortable reading column */
.gradio-container {
    max-width: 920px !important;
    margin: 0 auto !important;
    padding-top: 1.5rem !important;
}

/* Header */
.gradio-container h1 {
    font-weight: 600 !important;
    letter-spacing: -0.02em !important;
    color: #0f172a !important;
    margin-bottom: 0.25rem !important;
}
.markdown { color: #475569 !important; line-height: 1.55 !important; }

/* Chat messages */
.message { font-size: 15px !important; line-height: 1.6 !important; }
.message-bubble-border { border-color: #e2e8f0 !important; }

/* Tool-call accordion blocks — subdued so they don't compete with the answer */
.metadata-message,
[class*="metadata"] .message {
    opacity: 0.85;
    font-size: 13.5px !important;
}
[class*="metadata"] code,
[class*="metadata"] pre {
    background: #f1f5f9 !important;
    color: #475569 !important;
    border-radius: 6px !important;
}

/* Examples row — make them feel like quick-pick buttons */
.gr-button.gr-sample-button,
.gr-button[id*="example"] {
    background: #ffffff !important;
    border: 1px solid #e2e8f0 !important;
    color: #334155 !important;
    font-weight: 500 !important;
}
.gr-button.gr-sample-button:hover,
.gr-button[id*="example"]:hover {
    background: #f1f5f9 !important;
    border-color: #cbd5e1 !important;
}

/* Hide the Gradio footer for a cleaner look */
footer { display: none !important; }
"""


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

    with gr.Blocks(title="polilabs", analytics_enabled=False) as demo:
        gr.ChatInterface(
            fn=respond,
            title="polilabs",
            description=DESCRIPTION,
            examples=EXAMPLES,
            cache_examples=False,
            chatbot=gr.Chatbot(
                height=560,
                label="Conversation",
                avatar_images=(None, None),
            ),
            textbox=gr.Textbox(
                placeholder="Ask about an AI-governance bill...",
                autofocus=True,
                container=False,
            ),
        )

    demo.launch(
        server_port=args.port,
        share=args.share,
        inbrowser=not args.share,
        theme=THEME,
        css=CUSTOM_CSS,
    )


if __name__ == "__main__":
    main()
