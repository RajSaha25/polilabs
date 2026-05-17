"""polilabs agent-facing API — six primitives.

See api/SPEC.md for the design contract. Implementations are deferred to
Phase 2; this module locks the type contract that future code must satisfy.

The six primitives are the ONLY supported way for an agent to query the
corpus. Lower-level direct DB/file access is for ingestion and tooling,
not for agents.
"""
from __future__ import annotations

from datetime import date
from typing import Literal

from .types import (
    AdjacencySummary,
    AgreementScore,
    Bill,
    BillVersion,
    CitationEdge,
    CitationGraph,
    CitationType,
    CoverageReport,
    Provenance,
    ResolvedCitation,
    ResolvedRef,
    SearchHit,
    SearchResults,
    Section,
    SectionRef,
    SourceFreshness,
    Stream,
    StreamStatus,
    Tier,
)

__all__ = [
    "search_corpus",
    "get_bill",
    "get_section",
    "get_citation_graph",
    "resolve_citation",
    "corpus_coverage",
    # types re-exported for callers
    "AdjacencySummary",
    "AgreementScore",
    "Bill",
    "BillVersion",
    "CitationEdge",
    "CitationGraph",
    "CitationType",
    "CoverageReport",
    "Provenance",
    "ResolvedCitation",
    "ResolvedRef",
    "SearchHit",
    "SearchResults",
    "Section",
    "SectionRef",
    "SourceFreshness",
    "Stream",
    "StreamStatus",
    "Tier",
]


def search_corpus(
    query: str,
    *,
    date_range: tuple[date, date] | None = None,
    congresses: list[int] | None = None,
    tier: Tier | None = None,
    streams: list[Stream] | None = None,
    limit: int = 10,
    offset: int = 0,
) -> SearchResults:
    """Free-text search across the corpus. Returns ranked lightweight hits — never full text."""
    raise NotImplementedError("Phase 2: search_corpus")


def get_bill(bill_id: str) -> Bill:
    """Bill metadata + section table of contents. Does NOT return full text."""
    raise NotImplementedError("Phase 2: get_bill")


def get_section(section_id: str, *, as_of: date | None = None) -> Section:
    """Verbatim text of one section with canonical citation. as_of for point-in-time."""
    raise NotImplementedError("Phase 2: get_section")


def get_citation_graph(
    section_id: str,
    *,
    depth: int = 1,
    edge_types: list[CitationType] | None = None,
    direction: Literal["out", "in", "both"] = "both",
    max_nodes: int = 50,
) -> CitationGraph:
    """Typed citation graph around a section, bounded depth and size."""
    raise NotImplementedError("Phase 2: get_citation_graph")


def resolve_citation(citation_string: str) -> ResolvedCitation:
    """Parse a free-text citation to canonical IDs. Returns all candidates when ambiguous."""
    raise NotImplementedError("Phase 2: resolve_citation")


def corpus_coverage() -> CoverageReport:
    """Introspect corpus: date ranges, congresses, totals, out-of-scope streams, known gaps."""
    raise NotImplementedError("Phase 2: corpus_coverage")
