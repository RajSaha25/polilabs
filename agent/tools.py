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
    topic: str = "ai_governance",
    tier: str | None = None,
    congress: int | None = None,
    limit: int = 5,
) -> str:
    """Search a topic-scoped corpus by free-text query.

    Hybrid retrieval under the hood: BM25 over title+section text,
    bge-small-en-v1.5 dense embeddings over section text, fused via RRF.
    Pass `topic="redistricting"` for the redistricting corpus; default
    `"ai_governance"` preserves pre-P3 behavior.
    """
    try:
        result = api.search_corpus(
            query,
            topic=topic,
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


def tool_get_defined_terms(bill_id: str) -> str:
    """Get all DefinedTerm nodes scoped under a bill."""
    try:
        result = api.get_defined_terms(bill_id)
        return _dump(result)
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def tool_get_amendments(bill_id: str) -> str:
    """Get all AmendmentOperations issued by a bill."""
    try:
        result = api.get_amendments(bill_id)
        return _dump(result)
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def tool_get_amendments_targeting(statute_section_id: str) -> str:
    """Get all amendments in the corpus targeting a given USC section."""
    try:
        result = api.get_amendments_targeting(statute_section_id)
        return _dump(result)
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def tool_find_bills_defining(
    term: str,
    *,
    definition_type: str | None = None,
    by_reference_to: str | None = None,
    also_match: list[str] | None = None,
) -> str:
    """Find every bill that formally defines a given term — one call."""
    try:
        if definition_type not in (None, "direct", "by_reference"):
            return json.dumps({"error": f"definition_type must be 'direct' | 'by_reference' | null, got {definition_type!r}"})
        result = api.find_bills_defining(
            term,
            definition_type=definition_type,  # type: ignore[arg-type]
            by_reference_to=by_reference_to,
            also_match=also_match,
        )
        return _dump(result)
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def tool_find_bills_amending(statute_section_id: str) -> str:
    """Per-bill rollup of bills amending a USC section — one call."""
    try:
        result = api.find_bills_amending(statute_section_id)
        return _dump(result)
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def tool_find_definitions_of(term: str) -> str:
    """Every bill's definition of a term, side by side — one call."""
    try:
        result = api.find_definitions_of(term)
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
    "get_defined_terms": (
        "Get every defined term scoped under a bill. Each term carries: "
        "surface form (the term being defined), definition_type ('direct' "
        "if the bill states the meaning itself; 'by_reference' if the bill "
        "says 'has the meaning given such term in [U.S.C. citation]'), "
        "definition_text (verbatim), and — for by_reference terms — the "
        "U.S.C. target. Use this BEFORE making claims about what a bill "
        "means by 'AI', 'frontier model', 'covered entity', etc.: the "
        "same surface form is defined differently across bills, and "
        "conflating definitions is a top hallucination cause. The "
        "defining_section_citation field gives you the exact 'Sec. X(y)(z) "
        "of H.R. N' to quote."
    ),
    "get_amendments": (
        "Get every amendment operation a bill issues: what statute it "
        "changes, what operation (insert / strike / strike_and_insert / "
        "add_at_end / replace / repeal / redesignate), and the verbatim "
        "before/after text. Use this to answer 'what does this bill "
        "actually change about existing law?' "
        "target_text_unverified=true on every operation in v1: we have "
        "not yet ingested OLRC U.S. Code text, so we cannot verify that "
        "before_text matches the statute as it stands today. Always "
        "report this caveat when discussing amendments."
    ),
    "get_amendments_targeting": (
        "Get every amendment operation in the corpus that targets a "
        "given U.S. Code section. Use this to answer 'what other bills "
        "this session amend the same statute?' Accepts URN form "
        "('statute:us/usc/5/552'), slash shorthand ('5/552'), or prose "
        "form ('5 U.S.C. 552'). Like get_amendments, all results are "
        "target_text_unverified=true until USC ingestion lands."
    ),
    "find_bills_defining": (
        "AGGREGATE: Every bill in the corpus that formally defines a "
        "given term, in ONE call. Use this for 'which bills define X' "
        "and 'list every bill defining X by reference to USC Y' style "
        "questions. PREFER over the search → loop get_defined_terms "
        "pattern. Accepts optional filters: definition_type "
        "('direct' | 'by_reference'), by_reference_to (USC citation — "
        "implies by_reference), and also_match (list of synonym surface "
        "forms to OR in, e.g. ['AI'] when the primary term is "
        "'artificial intelligence' — bills frequently define the "
        "abbreviation as the canonical term). Returns the COMPLETE list "
        "— no pagination."
    ),
    "find_bills_amending": (
        "AGGREGATE: Per-bill rollup of every bill that amends a given "
        "U.S. Code section, in ONE call. Returns one row per bill with "
        "operation count + distinct operation types. PREFER over "
        "get_amendments_targeting when you only need to know WHICH bills "
        "amend a statute (e.g. 'list every bill amending 15 U.S.C. "
        "9401'); use get_amendments_targeting only when you need the "
        "operation-level detail (before/after text, locator)."
    ),
    "find_definitions_of": (
        "AGGREGATE: Every bill's verbatim definition of a single term, "
        "side by side, in ONE call. Use for cross-bill consensus or "
        "divergence analysis: 'how do bills define foundation model?', "
        "'are definitions of AI consistent across the corpus?'. Returns "
        "definition_text (verbatim) + definition_type + by_reference "
        "target for each. Case-insensitive exact match on surface form."
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
    "get_defined_terms": {
        "type": "object",
        "properties": {
            "bill_id": {"type": "string", "description": "Bill identifier; legacy ('119-hr-1736') or URN ('bill:us/119/hr/1736')."},
        },
        "required": ["bill_id"],
    },
    "get_amendments": {
        "type": "object",
        "properties": {
            "bill_id": {"type": "string", "description": "Bill identifier; legacy ('119-hr-8516') or URN ('bill:us/119/hr/8516')."},
        },
        "required": ["bill_id"],
    },
    "get_amendments_targeting": {
        "type": "object",
        "properties": {
            "statute_section_id": {"type": "string", "description": "U.S. Code section: URN ('statute:us/usc/5/552'), slash ('5/552'), or prose ('5 U.S.C. 552')."},
        },
        "required": ["statute_section_id"],
    },
    "find_bills_defining": {
        "type": "object",
        "properties": {
            "term": {"type": "string", "description": "Surface form of the term being defined (e.g. 'artificial intelligence'). Case-insensitive exact match."},
            "definition_type": {"type": "string", "enum": ["direct", "by_reference"], "description": "Filter: 'direct' = bill defines with own text; 'by_reference' = bill defers to another statute. Omit for both."},
            "by_reference_to": {"type": "string", "description": "USC citation the bill's definition cross-references (e.g. '15 U.S.C. 9401' or '15/9401'). Implies definition_type='by_reference'."},
            "also_match": {"type": "array", "items": {"type": "string"}, "description": "Additional surface forms to OR with `term` (e.g. ['AI'] when term is 'artificial intelligence')."},
        },
        "required": ["term"],
    },
    "find_bills_amending": {
        "type": "object",
        "properties": {
            "statute_section_id": {"type": "string", "description": "U.S. Code section: URN ('statute:us/usc/15/9401'), slash ('15/9401'), or prose ('15 U.S.C. 9401')."},
        },
        "required": ["statute_section_id"],
    },
    "find_definitions_of": {
        "type": "object",
        "properties": {
            "term": {"type": "string", "description": "Surface form to look up across the corpus."},
        },
        "required": ["term"],
    },
}


TOOL_FUNCTIONS = {
    "search_corpus": tool_search_corpus,
    "get_bill": tool_get_bill,
    "get_section": tool_get_section,
    "resolve_citation": tool_resolve_citation,
    "corpus_coverage": tool_corpus_coverage,
    "get_citation_graph": tool_get_citation_graph,
    "get_defined_terms": tool_get_defined_terms,
    "get_amendments": tool_get_amendments,
    "get_amendments_targeting": tool_get_amendments_targeting,
    "find_bills_defining": tool_find_bills_defining,
    "find_bills_amending": tool_find_bills_amending,
    "find_definitions_of": tool_find_definitions_of,
}


SYSTEM_PROMPT = """You are polilabs-agent, a citation-accurate research assistant for a queryable database of US federal AI-governance legislation.

The corpus is small and deliberate: 191 bills from the 118th and 119th US Congress (2023–present) that primarily or substantially concern AI, ML, generative AI, frontier models, automated decision systems, or facial recognition. v1 covers legislation only — regulatory actions (FTC, NIST, Commerce) and executive orders are explicitly out of scope.

Every claim about legislation MUST come from the tools. Never reconstruct a citation from prose or training data — quote the `canonical_citation` field that get_section returns. If a fact is not in the tool output, do not assert it.

## CRITICAL: prefer aggregate primitives over search → loop patterns

For ANY question of the shape "which bills do X" or "list every bill that Y" — DO NOT search_corpus and then loop drill-in calls. Use the aggregate primitive that answers the whole question in one call:

  • "Which bills define 'AI' by reference to 15 U.S.C. 9401?"
      → find_bills_defining("artificial intelligence", by_reference_to="15/9401", also_match=["AI"])
      NOT: search_corpus → loop get_defined_terms

  • "Which bills define 'AI' directly with their own text?"
      → find_bills_defining("artificial intelligence", definition_type="direct", also_match=["AI"])
      NOT: search_corpus → loop get_defined_terms

  • "Which bills amend 15 U.S.C. 9401?"
      → find_bills_amending("15 U.S.C. 9401")
      NOT: search_corpus → loop get_amendments

  • "How does each bill define 'foundation model'?"
      → find_definitions_of("foundation model")
      NOT: search_corpus → loop get_defined_terms

These primitives return the COMPLETE list with no pagination — when one returns N results, that's the entire answer. Bills frequently define abbreviations ("AI", "GAI") as the canonical term — pass synonyms via `also_match=[...]` rather than running multiple queries.

## Workflow for narrower questions

  1. search_corpus — discover relevant bills. Use when there's no aggregate primitive for the question. Pay attention to the `pagination_hint` field — it tells you whether to paginate or switch tools.
  2. get_bill — bill metadata + section table of contents. No body text.
  3. get_section — verbatim section text + the canonical citation you must quote. The `adjacency_summary` field reports how many statute citations this section makes; if it's >0, call get_citation_graph to see them.
  4. get_citation_graph — typed citation graph around a section (depth=1). Use for "what does this section cite?" Always cite the target's `canonical_citation` field verbatim.
  5. get_defined_terms — every term ONE bill formally defines. Use when the question is about a single bill ("what does H.R. 7913 define as a generative AI system?"). For cross-bill questions, use find_bills_defining / find_definitions_of instead.
  6. get_amendments — what does ONE bill change about existing law? Returns each AmendmentOperation with before/after text. target_text_unverified=true in v1; mention the caveat when summarizing.
  7. get_amendments_targeting — operation-level detail of every change to a statute. Use only when you need the before/after text; otherwise prefer find_bills_amending (compact, per-bill rollup).
  8. resolve_citation — turn a free-text citation like 'Sec. 3(a)(1) of H.R. 1736' into a section_id.
  9. corpus_coverage — when asked about scope, or when a search returns nothing.

When you cite a section, format like: "Sec. 3(a)(1) of H.R. 1736, 119th Cong." (the exact `canonical_citation` string).

If something is outside the corpus (regulatory, executive, pre-2023, or a bill that's genuinely missing), say so explicitly. Do not bluff.

## Response style

Answer like a briefing for a busy legislative researcher, not a chat.

- No filler. Never open with "Great question", "Certainly", "Of course", or any warm-up. The first sentence is the answer.
- Match length to the question. A narrow question gets a short, direct answer; a broad one gets full detail. Don't restate the question back, and don't tack on a closing summary or a "would you like me to…" sign-off.
- Flag uncertainty before it costs the reader. If a fact, date, number, or citation is not in the tool output, say so explicitly — never fill a gap with plausible-sounding content.
- Honest over optimistic. Say plainly where the corpus is silent or a bill does not reach an issue, rather than padding the answer.
- Be punchy. Every sentence should carry a fact or a citation. Use short headings and tight lists when they aid scanning; drop them when they don't.
- Comparisons and analogies only when they genuinely clarify the law — not for color."""
