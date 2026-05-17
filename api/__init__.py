"""polilabs agent-facing API.

See api/SPEC.md for the design contract. Implementations live in api/_impl.py
and are backed by data/polilabs.db (SQLite, FTS) + data/polilabs.kuzu (graph).

These primitives are the ONLY supported way for an agent to query the
corpus. Lower-level direct DB/file access is for ingestion and tooling,
not for agents.
"""
from __future__ import annotations

from ._impl import (
    corpus_coverage,
    get_amendments,
    get_amendments_targeting,
    get_bill,
    get_citation_graph,
    get_defined_terms,
    get_section,
    resolve_citation,
    search_corpus,
)
from .types import (
    AdjacencySummary,
    AgreementScore,
    Amendment,
    AmendmentOperationType,
    AmendmentsResult,
    AmendmentsTargetingResult,
    Bill,
    BillVersion,
    CitationEdge,
    CitationGraph,
    CitationType,
    CoverageReport,
    DefinedTerm,
    DefinedTermsResult,
    DefinitionScope,
    DefinitionType,
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
    "get_defined_terms",
    "get_amendments",
    "get_amendments_targeting",
    "resolve_citation",
    "corpus_coverage",
    # types re-exported for callers
    "AdjacencySummary",
    "AgreementScore",
    "Amendment",
    "AmendmentOperationType",
    "AmendmentsResult",
    "AmendmentsTargetingResult",
    "Bill",
    "BillVersion",
    "CitationEdge",
    "CitationGraph",
    "CitationType",
    "CoverageReport",
    "DefinedTerm",
    "DefinedTermsResult",
    "DefinitionScope",
    "DefinitionType",
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
