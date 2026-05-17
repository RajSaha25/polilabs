"""Type definitions for the polilabs agent-facing API.

See api/SPEC.md for the design contract these types implement.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal

Stream = Literal["legislation", "regulatory", "executive"]
Tier = Literal["A", "B"]
CitationType = Literal["amends", "repeals", "cites", "references"]


@dataclass(frozen=True)
class AgreementScore:
    """Multi-source agreement signal. Populated in Phase 4."""
    sources_agreeing: int
    sources_total: int
    fields_in_disagreement: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Provenance:
    sources: list[str]
    last_verified: datetime
    agreement: AgreementScore | None = None
    notes: str | None = None


@dataclass(frozen=True)
class SectionRef:
    """Lightweight reference to a section — used in indexes and graph nodes."""
    section_id: str
    bill_id: str
    heading: str
    parent_section_id: str | None
    version_count: int


@dataclass(frozen=True)
class BillVersion:
    label: str           # "introduced" | "engrossed" | "enrolled" | "public-law" | etc.
    version_date: date
    package_id: str      # GovInfo package id


@dataclass(frozen=True)
class SearchHit:
    bill_id: str
    title: str
    short_title: str | None
    summary: str | None
    sponsor: str
    congress: int
    introduced_date: date
    tier: Tier
    stream: Stream
    matched_keywords: list[str]
    relevance_score: float
    provenance: Provenance


@dataclass(frozen=True)
class SearchResults:
    hits: list[SearchHit]
    total: int
    query: str
    coverage_note: str
    in_scope: bool  # distinguishes 0-hits-in-scope from query-out-of-scope


@dataclass(frozen=True)
class Bill:
    bill_id: str
    congress: int
    bill_type: str
    bill_number: int
    title: str
    short_title: str | None
    sponsor: str
    cosponsors: list[str]
    introduced_date: date
    latest_action: str
    status: str
    tier: Tier
    stream: Stream
    sections: list[SectionRef]
    versions: list[BillVersion]
    provenance: Provenance


@dataclass(frozen=True)
class AdjacencySummary:
    citations_out_count: int
    citations_in_count: int
    by_type_out: dict[CitationType, int]
    by_type_in: dict[CitationType, int]


@dataclass(frozen=True)
class Section:
    section_id: str
    bill_id: str
    heading: str
    text: str | None              # None if as_of predates any known version
    canonical_citation: str
    parent_section_id: str | None
    child_section_ids: list[str]
    version_date: date | None
    version_label: str | None
    is_current: bool
    adjacency_summary: AdjacencySummary
    provenance: Provenance
    not_found: bool = False


@dataclass(frozen=True)
class CitationEdge:
    source_id: str
    target_id: str
    type: CitationType
    provenance: Provenance


@dataclass(frozen=True)
class CitationGraph:
    root_section_id: str
    nodes: list[SectionRef]
    edges: list[CitationEdge]
    truncated: bool


@dataclass(frozen=True)
class ResolvedRef:
    section_id: str
    confidence: float
    interpretation_note: str


@dataclass(frozen=True)
class ResolvedCitation:
    input: str
    resolved: list[ResolvedRef]
    is_ambiguous: bool
    provenance: Provenance


@dataclass(frozen=True)
class SourceFreshness:
    source: str           # e.g. "congress.gov", "govinfo", "olrc"
    last_fetched: datetime


@dataclass(frozen=True)
class StreamStatus:
    stream: Stream
    reason: str | None    # explanation when out-of-scope


@dataclass(frozen=True)
class CoverageReport:
    corpus_version: str
    criteria_version: str
    last_updated: datetime
    streams_in_scope: list[StreamStatus]
    streams_out_of_scope: list[StreamStatus]
    date_range: tuple[date, date]
    congresses: list[int]
    bill_count_by_tier: dict[Tier, int]
    source_freshness: list[SourceFreshness]
    known_gaps: list[str]
