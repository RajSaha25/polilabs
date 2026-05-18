"""Interactive chat REPL — drive polilabs from the terminal.

Uses the Anthropic SDK's beta tool runner to handle the agentic loop. Each of
the six polilabs API primitives becomes a tool Claude can call. The system
prompt constrains the agent to cite verbatim from get_section, never
reconstruct citations, and acknowledge corpus-scope limits honestly.

Run after `data/polilabs.db` is built and ANTHROPIC_API_KEY is in .env:
    python scripts/chat.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import anthropic
from anthropic import beta_tool

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


# ---- @beta_tool wrappers ----
# Type annotations and docstrings drive schema generation. Keep them precise.


@beta_tool
def search_corpus(
    query: str,
    tier: str | None = None,
    congress: int | None = None,
    limit: int = 5,
) -> str:
    """Search the polilabs AI-governance corpus by free-text query.

    Returns ranked lightweight bill hits (title, sponsor, summary preview,
    relevance score) — NEVER full bill text. Use this to discover relevant
    bills, then call get_bill / get_section for details. Multi-word queries
    are AND'd; for phrase search use double-quoted FTS5 syntax.

    Args:
        query: Free-text query, e.g. "frontier model" or "Section 230".
        tier: Optional 'A' (primary AI-gov) or 'B' (substantial AI provisions).
        congress: Optional Congress number filter, 118 or 119.
        limit: Max hits to return (1-25, default 5).
    """
    return tool_search_corpus(query, tier=tier, congress=congress, limit=limit)


@beta_tool
def get_bill(bill_id: str) -> str:
    """Get a bill's metadata and top-level section table of contents.

    Returns sponsor, cosponsors, latest action, tier, sections list (each
    with section_id and heading), and available bill versions. Does NOT
    return full bill text — call get_section on a specific section_id.

    Args:
        bill_id: Bill identifier like '118-hr-5949' or '119-s-1071'.
    """
    return tool_get_bill(bill_id)


@beta_tool
def get_section(section_id: str, as_of: str | None = None) -> str:
    """Get the verbatim text of a single section, with its canonical citation.

    The response includes a `canonical_citation` string (e.g. 'Sec. 3(a)(1)
    of H.R. 1736, 119th Cong.') — ALWAYS quote this verbatim when citing
    the section. Do not reconstruct citations from prose.

    Args:
        section_id: Section ID from a Bill's section list.
        as_of: Optional ISO date YYYY-MM-DD for point-in-time queries.
            v1 stores one canonical version per bill so this returns the
            current version with a provenance note explaining the limit.
    """
    return tool_get_section(section_id, as_of=as_of)


@beta_tool
def resolve_citation(citation_string: str) -> str:
    """Parse a free-text legislative citation into canonical section IDs.

    Returns all matching candidates with confidence scores. Returns an
    empty `resolved` list with a note when the citation form is unsupported
    or the bill is not in the corpus.

    Args:
        citation_string: e.g. 'Sec. 3(a)(1) of H.R. 1736, 119th Cong.'.
    """
    return tool_resolve_citation(citation_string)


@beta_tool
def corpus_coverage() -> str:
    """Report exactly what is in the corpus and what is not.

    Use this when the user asks about scope or coverage, OR when a query
    returns no hits — it gives you a structured answer that distinguishes
    'in scope but no match' from 'out of v1 scope.'
    """
    return tool_corpus_coverage()


@beta_tool
def get_citation_graph(
    section_id: str,
    direction: str = "both",
    max_nodes: int = 25,
) -> str:
    """Get the typed citation graph around a section (depth=1).

    Returns a list of `nodes` and `edges`: which statutes the section
    cites (outbound) and which sections cite this one (inbound). PR2
    populates CITES_EXTERNAL edges to U.S. Code sections; AMENDS /
    repeals / references land in later PRs.

    Args:
        section_id: Section ID (legacy '119-hr-1736::H7CA...' or URN
            'bill:us/119/hr/1736::H7CA...') — typically copied from a
            get_bill or get_section response.
        direction: 'out' (this section cites X), 'in' (X cites this
            section), or 'both'. Default: both.
        max_nodes: Cap per direction (1-100). Default: 25.
    """
    return tool_get_citation_graph(section_id, direction=direction, max_nodes=max_nodes)


@beta_tool
def get_defined_terms(bill_id: str) -> str:
    """Get every term the bill formally defines.

    Each term carries surface_form, definition_type ('direct' or
    'by_reference'), definition_text (verbatim), defining_section_citation
    (the exact 'Sec. X(y)(z) of H.R. N' to quote), and — for
    by_reference terms — the U.S.C. target (e.g. '15 U.S.C. 9401').

    CRITICAL: same surface form often has different definitions across
    bills. Always call this before answering definitional questions —
    don't rely on prior knowledge.

    Args:
        bill_id: Bill identifier (legacy '119-hr-1736' or URN
            'bill:us/119/hr/1736').
    """
    return tool_get_defined_terms(bill_id)


@beta_tool
def get_amendments(bill_id: str) -> str:
    """Get every amendment a bill makes to existing U.S. Code.

    Each Amendment carries operation_type, target_canonical_citation,
    target_locator_json (structured target locator), and verbatim
    before_text + after_text. Use to answer 'what does this bill
    actually change about existing law?'

    target_text_unverified is True on every operation in v1 — we have
    not yet ingested OLRC U.S. Code text, so before_text has not been
    checked against the statute as it stands today. Always mention this
    caveat in summaries.

    Args:
        bill_id: Bill identifier (legacy '119-hr-8516' or URN).
    """
    return tool_get_amendments(bill_id)


@beta_tool
def get_amendments_targeting(statute_section_id: str) -> str:
    """Get all amendments in the corpus targeting a U.S. Code section.

    Use when researching "what other bills this session amend the same
    statute?" — surfaces every (bill, section, operation) triple that
    touches a given USC section.

    Args:
        statute_section_id: URN ('statute:us/usc/5/552'), slash form
            ('5/552'), or prose ('5 U.S.C. 552').
    """
    return tool_get_amendments_targeting(statute_section_id)


@beta_tool
def find_bills_defining(
    term: str,
    definition_type: str | None = None,
    by_reference_to: str | None = None,
    also_match: list[str] | None = None,
) -> str:
    """AGGREGATE: every bill in the corpus that formally defines a term — one call.

    PREFER this over the search_corpus → loop get_defined_terms pattern for
    "which bills define X" style questions. Returns the COMPLETE list with
    no pagination. Bills frequently define abbreviations as the canonical
    term — pass synonyms via also_match (e.g. ['AI'] when querying for
    'artificial intelligence') rather than re-running the query.

    Args:
        term: Surface form of the term (case-insensitive exact match).
        definition_type: 'direct' (own text) or 'by_reference' (defers to USC).
        by_reference_to: USC citation for by_reference filter (e.g. '15 U.S.C. 9401').
            Implies definition_type='by_reference'.
        also_match: Additional surface forms to OR with `term`.
    """
    return tool_find_bills_defining(
        term, definition_type=definition_type,
        by_reference_to=by_reference_to, also_match=also_match,
    )


@beta_tool
def find_bills_amending(statute_section_id: str) -> str:
    """AGGREGATE: per-bill rollup of bills amending a USC section — one call.

    Returns one row per bill with operation count + distinct operation types.
    PREFER over get_amendments_targeting when you only need to know WHICH
    bills amend a statute.

    Args:
        statute_section_id: URN, slash ('15/9401'), or prose ('15 U.S.C. 9401').
    """
    return tool_find_bills_amending(statute_section_id)


@beta_tool
def find_definitions_of(term: str) -> str:
    """AGGREGATE: every bill's verbatim definition of a term, side by side — one call.

    Use for cross-bill consensus / divergence analysis.

    Args:
        term: Surface form to look up across the corpus (case-insensitive).
    """
    return tool_find_definitions_of(term)


TOOLS = [
    search_corpus, get_bill, get_section, resolve_citation,
    corpus_coverage, get_citation_graph, get_defined_terms,
    get_amendments, get_amendments_targeting,
    find_bills_defining, find_bills_amending, find_definitions_of,
]


def _check_db_ready() -> None:
    db = Path(os.environ.get("POLILABS_DB", "data/polilabs.db"))
    if not db.exists():
        print(f"[error] polilabs.db not found at {db}", file=sys.stderr)
        print("        Build it first: python scripts/build_index.py", file=sys.stderr)
        sys.exit(1)


def _check_anthropic_key() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("[error] ANTHROPIC_API_KEY not set in .env", file=sys.stderr)
        print("        Get one at https://console.anthropic.com/ and add to .env", file=sys.stderr)
        sys.exit(1)


def _render_message(message) -> bool:
    """Print text/tool_use blocks from a Claude message. Returns True if any text was printed."""
    printed_text = False
    for block in message.content:
        if block.type == "text" and block.text:
            print(block.text, end="", flush=True)
            printed_text = True
        elif block.type == "tool_use":
            args_preview = ", ".join(f"{k}={v!r}" for k, v in (block.input or {}).items())
            if len(args_preview) > 100:
                args_preview = args_preview[:97] + "..."
            print(f"\n\033[2m  → {block.name}({args_preview})\033[0m", flush=True)
    return printed_text


def main() -> None:
    _check_db_ready()
    _check_anthropic_key()
    client = anthropic.Anthropic()

    print("\033[1mpolilabs chat\033[0m — AI-governance legislation corpus, 191 bills, 118th-119th Congress")
    print("Type a question. Use \033[2m/reset\033[0m to clear, \033[2m/exit\033[0m to quit.\n")

    messages: list = []

    while True:
        try:
            user_input = input("\033[1m>\033[0m ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return

        if not user_input:
            continue
        if user_input in ("/exit", "/quit"):
            return
        if user_input == "/reset":
            messages = []
            print("\033[2m(conversation reset)\033[0m\n")
            continue

        messages.append({"role": "user", "content": user_input})

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
                messages=messages,
            )
            last = None
            for message in runner:
                _render_message(message)
                last = message
            print()  # newline after final response

            if last is not None:
                messages.append({"role": "assistant", "content": last.content})
        except anthropic.APIError as e:
            print(f"\n\033[31m[api error] {type(e).__name__}: {e}\033[0m", file=sys.stderr)
        except Exception as e:
            print(f"\n\033[31m[error] {type(e).__name__}: {e}\033[0m", file=sys.stderr)


if __name__ == "__main__":
    main()
