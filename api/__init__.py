"""polilabs agent-facing API — six primitives.

See api/SPEC.md for the design contract. Implementations live in api/_impl.py
and are backed by data/polilabs.db (build with `python scripts/build_index.py`).

The six primitives are the ONLY supported way for an agent to query the
corpus. Lower-level direct DB/file access is for ingestion and tooling,
not for agents.
"""
from __future__ import annotations

from ._impl import (
    corpus_coverage,
    get_bill,
    get_citation_graph,
    get_section,
    resolve_citation,
    search_corpus,
)
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


