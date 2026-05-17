"""Shared tool implementations — used by both the chat REPL and the MCP server.

Each tool wraps one of the six api/SPEC.md primitives. The wrapper:
  - Accepts JSON-friendly arguments (strings, ints, simple types)
  - Calls the api.* function
  - Serializes the typed dataclass response back to a JSON string

This is the boundary between the typed Python API (frozen dataclasses with
date/datetime objects) and the agent surface (JSON-serializable text).

The same set of tools backs both surfaces:
  - The Anthropic SDK chat REPL via @beta_tool wrappers (scripts/chat.py)
  - The MCP server via mcp.types.Tool entries (mcp_server.py)
"""
from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from typing import Any

import api


def _json_default(o: Any) -> Any:
    if isinstance(o, (date, datetime)):
        return o.isoformat()
    raise TypeError(f"Object of type {type(o).__name__} is not JSON serializable")


def _dump(obj: Any) -> str:
    """Serialize a dataclass (or plain object) to a JSON string."""
    if is_dataclass(obj):
        data = asdict(obj)
    else:
        data = obj
    return json.dumps(data, default=_json_default, indent=2)


# -----------------------------------------------------------------------------
# Tool implementations — return JSON strings, not typed objects.
# Errors are returned as JSON {"error": ...} rather than raising, so the
# agent sees a structured failure instead of a stack trace.
# -----------------------------------------------------------------------------


def tool_search_corpus(
    query: str,
    *,
    tier: str | None = None,
    congress: int | None = None,
    limit: int = 5,
) -> str:
    """Search the AI-governance corpus by free-text query."""
    try:
        result = api.search_corpus(
            query,
            tier=tier if tier in ("A", "B") else None,
            congresses=[congress] if congress else None,
            limit=min(max(limit, 1), 25),
        )
        return _dump(result)
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def tool_get_bill(bill_id: str) -> str:
    """Get a bill's metadata and section table of contents."""
    try:
        result = api.get_bill(bill_id)
        return _dump(result)
    except KeyError as e:
        return json.dumps({"not_found": True, "error": str(e)})
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def tool_get_section(section_id: str, *, as_of: str | None = None) -> str:
    """Get verbatim text of a section with canonical citation."""
    try:
        as_of_date = date.fromisoformat(as_of) if as_of else None
    except ValueError:
        return json.dumps({"error": f"as_of must be ISO date (YYYY-MM-DD), got {as_of!r}"})
    try:
        result = api.get_section(section_id, as_of=as_of_date)
        return _dump(result)
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def tool_resolve_citation(citation_string: str) -> str:
    """Parse a free-text legislative citation into canonical section IDs."""
    try:
        result = api.resolve_citation(citation_string)
        return _dump(result)
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def tool_corpus_coverage() -> str:
    """Report what's in the corpus: congresses, date range, tier counts, known gaps."""
    try:
        result = api.corpus_coverage()
        return _dump(result)
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def tool_get_citation_graph(
    section_id: str,
    *,
    direction: str = "both",
    max_nodes: int = 25,
) -> str:
    """Get typed citation graph around a section (depth=1 in PR2)."""
    if direction not in ("out", "in", "both"):
        return json.dumps({"error": f"direction must be one of out|in|both, got {direction!r}"})
    try:
        result = api.get_citation_graph(
            section_id,
            direction=direction,  # type: ignore[arg-type]
            max_nodes=min(max(max_nodes, 1), 100),
        )
        return _dump(result)
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


# -----------------------------------------------------------------------------
# JSON-schema-compatible tool descriptors — used by the MCP server.
# The Anthropic SDK derives schemas from @beta_tool function signatures
# instead, but the human-readable descriptions are reused.
# -----------------------------------------------------------------------------

TOOL_DESCRIPTIONS = {
    "search_corpus": (
        "Search the polilabs AI-governance corpus by free-text query. "
        "Returns ranked lightweight bill hits (title, sponsor, summary preview, "
        "score) — never full bill text. Use this to discover relevant bills, "
        "then call get_bill / get_section for details."
    ),
    "get_bill": (
        "Get a bill's metadata, sponsor, cosponsors, latest action, and a "
        "table of contents of its top-level sections. Does NOT return full "
        "bill text — call get_section on a specific section_id for that."
    ),
    "get_section": (
        "Get the verbatim text of a single section, with its canonical "
        "citation (e.g. 'Sec. 3(a)(1) of H.R. 1736, 119th Cong.'). Always "
        "quote the canonical_citation when citing this text — do not "
        "reconstruct citations from prose. Optional as_of parameter for "
        "point-in-time queries (ISO date YYYY-MM-DD); v1 stores one "
        "canonical version per bill so this returns the current version "
        "with a provenance note."
    ),
    "resolve_citation": (
        "Parse a free-text legislative citation like "
        "'Sec. 3(a)(1) of H.R. 1736, 119th Cong.' into a canonical section "
        "ID. Returns all candidates when ambiguous; returns an empty list "
        "with a note when the citation form is not supported or the bill "
        "is not in the corpus."
    ),
    "corpus_coverage": (
        "Report exactly what is in the corpus: corpus and criteria versions, "
        "in-scope and out-of-scope streams (legislation in scope; regulatory "
        "and executive currently out of v1), date range, congresses, bill "
        "count per tier, source freshness, and known gaps. Call this when "
        "the user asks about scope or when a query returns no hits — it "
        "tells you what the corpus does and does not cover, so you can "
        "say 'I don't know' honestly instead of confabulating."
    ),
    "get_citation_graph": (
        "Get the typed citation graph around a section: which statutes it "
        "cites (outbound) and which sections cite it (inbound). PR2 "
        "populates CITES_EXTERNAL edges to U.S. Code sections; "
        "CITES_INTERNAL (Section→Section) and AMENDS / repeals / "
        "references land in later PRs. Accepts either legacy "
        "('119-hr-1736::H7CA...') or URN "
        "('bill:us/119/hr/1736::H7CA...') section IDs."
    ),
}


# JSON Schema for each tool — used by the MCP server.
TOOL_SCHEMAS = {
    "search_corpus": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Free-text query. Multi-word queries are AND'd as separate phrase tokens."},
            "tier": {"type": "string", "enum": ["A", "B"], "description": "Filter to Tier A (primary AI-governance) or B (substantial AI provisions). Optional."},
            "congress": {"type": "integer", "description": "Filter to a specific Congress (118 or 119). Optional."},
            "limit": {"type": "integer", "default": 5, "description": "Max hits to return (1-25)."},
        },
        "required": ["query"],
    },
    "get_bill": {
        "type": "object",
        "properties": {
            "bill_id": {"type": "string", "description": "Bill identifier like '118-hr-5949' or '119-s-1071'."},
        },
        "required": ["bill_id"],
    },
    "get_section": {
        "type": "object",
        "properties": {
            "section_id": {"type": "string", "description": "Section identifier from a Bill's section list, e.g. '119-hr-1736::H42A...'."},
            "as_of": {"type": "string", "description": "Optional ISO date YYYY-MM-DD for point-in-time queries."},
        },
        "required": ["section_id"],
    },
    "resolve_citation": {
        "type": "object",
        "properties": {
            "citation_string": {"type": "string", "description": "Free-text citation, e.g. 'Sec. 3(a)(1) of H.R. 1736, 119th Cong.'."},
        },
        "required": ["citation_string"],
    },
    "corpus_coverage": {
        "type": "object",
        "properties": {},
    },
    "get_citation_graph": {
        "type": "object",
        "properties": {
            "section_id": {"type": "string", "description": "Section identifier; legacy ('119-hr-1736::H7CA...') or URN ('bill:us/119/hr/1736::H7CA...')."},
            "direction": {"type": "string", "enum": ["out", "in", "both"], "default": "both", "description": "Citation direction: 'out' = sections this cites; 'in' = sections that cite this; 'both' = both."},
            "max_nodes": {"type": "integer", "default": 25, "description": "Max nodes per direction (1-100)."},
        },
        "required": ["section_id"],
    },
}


TOOL_FUNCTIONS = {
    "search_corpus": tool_search_corpus,
    "get_bill": tool_get_bill,
    "get_section": tool_get_section,
    "resolve_citation": tool_resolve_citation,
    "corpus_coverage": tool_corpus_coverage,
    "get_citation_graph": tool_get_citation_graph,
}


SYSTEM_PROMPT = """You are polilabs-agent, a citation-accurate research assistant for a queryable database of US federal AI-governance legislation.

The corpus is small and deliberate: 191 bills from the 118th and 119th US Congress (2023–present) that primarily or substantially concern AI, ML, generative AI, frontier models, automated decision systems, or facial recognition. v1 covers legislation only — regulatory actions (FTC, NIST, Commerce) and executive orders are explicitly out of scope.

Every claim about legislation MUST come from the tools. Never reconstruct a citation from prose or training data — quote the `canonical_citation` field that get_section returns. If a fact is not in the tool output, do not assert it.

Workflow:
  1. search_corpus — discover relevant bills. The hit is lightweight; use to find bill_ids, then drill down.
  2. get_bill — bill metadata + section table of contents. No body text.
  3. get_section — verbatim section text + the canonical citation you must quote. The `adjacency_summary` field reports how many statute citations this section makes; if it's >0, call get_citation_graph to see them.
  4. get_citation_graph — typed citation graph around a section (PR2 ships outbound CITES_EXTERNAL edges to U.S. Code targets, depth=1). Use to answer "what does this section cite?" and to ground claims about which statutes a bill touches. Always cite the target's `canonical_citation` field verbatim.
  5. resolve_citation — when the user gives you a citation like 'Sec. 3(a)(1) of H.R. 1736', use this to find the section_id.
  6. corpus_coverage — when asked about scope, or when a search returns nothing, use this to give an honest answer about what is and isn't in the corpus.

When you cite a section, format like: "Sec. 3(a)(1) of H.R. 1736, 119th Cong." (the exact `canonical_citation` string).

If something is outside the corpus (regulatory, executive, pre-2023, or a bill the search misses), say so explicitly. Do not bluff."""
