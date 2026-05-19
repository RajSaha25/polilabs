"""Eval runner: drive Claude with the polilabs tools, capture final answers.

For each query in queries.yaml:
  1. Spawn an Anthropic tool_runner with the same six+three tool surface
     scripts/chat.py exposes.
  2. Send the query as a single user message.
  3. Iterate the tool runner, accumulating tool calls + text.
  4. Capture: the final answer text, the full tool-call trace (name +
     arguments + response), latency, token counts.
  5. Hand back to the scorer.

Supports a `--dry-run` mode that skips API calls — useful for verifying
queries.yaml parses, tools import cleanly, and the runner harness works
without burning API budget.
"""
from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Path setup so this module can be imported from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import yaml  # noqa: E402


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]
    response_text: str           # JSON string the tool returned
    response_summary: str        # one-line summary for the report


@dataclass
class QueryRun:
    query_id: str
    category: str
    question: str
    final_answer: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    error: str | None = None
    latency_s: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    aborted: bool = False


def load_queries(yaml_path: Path) -> list[dict[str, Any]]:
    data = yaml.safe_load(yaml_path.read_text())
    return data.get("queries", [])


def _summarize_tool_response(name: str, response_text: str) -> str:
    """Tiny one-line summary of a tool response for the run log."""
    try:
        obj = json.loads(response_text)
    except Exception:
        return f"<unparseable response, {len(response_text)} chars>"
    if isinstance(obj, dict):
        if "error" in obj:
            return f"error: {obj['error'][:80]}"
        if "not_found" in obj and obj.get("not_found"):
            return "not_found"
        # Common shape: { 'bills_or_terms_etc': [...], 'coverage_note': ... }
        for key in ("hits", "amendments", "terms", "edges", "resolved"):
            if key in obj and isinstance(obj[key], list):
                return f"{len(obj[key])} {key}"
        if "bill_id" in obj:
            return f"bill_id={obj['bill_id']}"
        if "section_id" in obj:
            return f"section={obj['section_id'][-50:]}"
    return f"<{type(obj).__name__}>"


def _dry_run(queries: list[dict[str, Any]]) -> list[QueryRun]:
    runs: list[QueryRun] = []
    for q in queries:
        runs.append(QueryRun(
            query_id=q["id"], category=q["category"], question=q["question"],
            final_answer="(dry run — no API call)",
            aborted=True,
        ))
    return runs


def run_queries(
    queries: list[dict[str, Any]],
    *,
    model: str = "claude-opus-4-7",
    max_tokens: int = 4096,
    max_tool_iterations: int = 12,
    dry_run: bool = False,
    verbose: bool = True,
) -> list[QueryRun]:
    """Run every query, return a list of QueryRun objects."""
    if dry_run:
        return _dry_run(queries)

    # Lazy import so dry-run mode works without anthropic + .env set up.
    import anthropic
    from anthropic import beta_tool

    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set. Create .env from .env.example and add "
            "your key, then re-run."
        )

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

    # Per-query recorder. The SDK's tool_runner executes tools inside its
    # iterator and we don't see tool_result blocks when iterating, so the
    # only honest way to capture (name, args, response) tuples is to wrap
    # each tool with a recorder that appends to this list before
    # returning. Reset at the top of every query.
    _recorder: list[ToolCall] = []

    def _record(name):
        def wrapper(fn):
            def wrapped(**kwargs):
                response = fn(**kwargs)
                _recorder.append(ToolCall(
                    name=name, arguments=dict(kwargs),
                    response_text=response,
                    response_summary=_summarize_tool_response(name, response),
                ))
                return response
            wrapped.__name__ = fn.__name__
            wrapped.__doc__ = fn.__doc__
            return wrapped
        return wrapper

    @beta_tool
    @_record("search_corpus")
    def search_corpus(query: str, tier: str | None = None,
                       congress: int | None = None, limit: int = 5) -> str:
        """Search the polilabs corpus by free-text query."""
        return tool_search_corpus(query, tier=tier, congress=congress, limit=limit)

    @beta_tool
    @_record("get_bill")
    def get_bill(bill_id: str) -> str:
        """Get a bill's metadata and section table of contents."""
        return tool_get_bill(bill_id)

    @beta_tool
    @_record("get_section")
    def get_section(section_id: str, as_of: str | None = None) -> str:
        """Get verbatim section text with canonical citation."""
        return tool_get_section(section_id, as_of=as_of)

    @beta_tool
    @_record("resolve_citation")
    def resolve_citation(citation_string: str) -> str:
        """Parse a free-text citation into canonical section IDs."""
        return tool_resolve_citation(citation_string)

    @beta_tool
    @_record("corpus_coverage")
    def corpus_coverage() -> str:
        """Report exactly what is in the corpus and what is not."""
        return tool_corpus_coverage()

    @beta_tool
    @_record("get_citation_graph")
    def get_citation_graph(section_id: str, direction: str = "both",
                           max_nodes: int = 25) -> str:
        """Typed citation graph around a section (depth=1)."""
        return tool_get_citation_graph(section_id, direction=direction, max_nodes=max_nodes)

    @beta_tool
    @_record("get_defined_terms")
    def get_defined_terms(bill_id: str) -> str:
        """Every term a bill formally defines."""
        return tool_get_defined_terms(bill_id)

    @beta_tool
    @_record("get_amendments")
    def get_amendments(bill_id: str) -> str:
        """Every amendment a bill makes to existing law."""
        return tool_get_amendments(bill_id)

    @beta_tool
    @_record("get_amendments_targeting")
    def get_amendments_targeting(statute_section_id: str) -> str:
        """Every amendment in the corpus targeting a U.S. Code section."""
        return tool_get_amendments_targeting(statute_section_id)

    @beta_tool
    @_record("find_bills_defining")
    def find_bills_defining(
        term: str,
        definition_type: str | None = None,
        by_reference_to: str | None = None,
        also_match: list[str] | None = None,
    ) -> str:
        """AGGREGATE: every bill defining a term, in one call. Prefer over search+loop."""
        return tool_find_bills_defining(
            term, definition_type=definition_type,
            by_reference_to=by_reference_to, also_match=also_match,
        )

    @beta_tool
    @_record("find_bills_amending")
    def find_bills_amending(statute_section_id: str) -> str:
        """AGGREGATE: per-bill rollup of bills amending a USC section."""
        return tool_find_bills_amending(statute_section_id)

    @beta_tool
    @_record("find_definitions_of")
    def find_definitions_of(term: str) -> str:
        """AGGREGATE: every bill's verbatim definition of a term, side by side."""
        return tool_find_definitions_of(term)

    TOOLS = [
        search_corpus, get_bill, get_section, resolve_citation,
        corpus_coverage, get_citation_graph, get_defined_terms,
        get_amendments, get_amendments_targeting,
        find_bills_defining, find_bills_amending, find_definitions_of,
    ]

    client = anthropic.Anthropic()
    runs: list[QueryRun] = []
    for i, q in enumerate(queries):
        run = QueryRun(query_id=q["id"], category=q["category"], question=q["question"])
        _recorder.clear()  # fresh recording per query
        if verbose:
            print(f"  [{i+1}/{len(queries)}] {q['id']:<32} {q['question'][:60]}")
        started = time.monotonic()
        try:
            runner = client.beta.messages.tool_runner(
                model=model,
                max_tokens=max_tokens,
                tools=TOOLS,
                system=[{
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=[{"role": "user", "content": q["question"]}],
            )

            iteration = 0
            final_text_parts: list[str] = []
            for message in runner:
                iteration += 1
                if iteration > max_tool_iterations:
                    run.aborted = True
                    run.error = f"exceeded max_tool_iterations ({max_tool_iterations})"
                    break
                run.input_tokens += getattr(message.usage, "input_tokens", 0) or 0
                run.output_tokens += getattr(message.usage, "output_tokens", 0) or 0
                for block in message.content:
                    if getattr(block, "type", None) == "text" and getattr(block, "text", ""):
                        final_text_parts.append(block.text)
            # The tool_runner yields assistant messages only; tool_use/
            # tool_result blocks are consumed internally. The wrapped tools
            # have appended every (name, args, response) into _recorder as
            # they fired — copy it onto the run now.
            run.tool_calls = list(_recorder)
            run.final_answer = "".join(final_text_parts).strip() or "(no final text)"
        except Exception as e:
            run.error = f"{type(e).__name__}: {e}"
            run.aborted = True
        finally:
            run.latency_s = time.monotonic() - started
        runs.append(run)
        if verbose:
            n_tools = len(run.tool_calls)
            status = "OK" if not run.error else f"ERR ({run.error[:60]})"
            print(f"      {status} · {n_tools} tool calls · "
                  f"{run.input_tokens}+{run.output_tokens}t · {run.latency_s:.1f}s")
    return runs
