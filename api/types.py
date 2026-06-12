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
    # Natural-language pagination cue. Practitioner consensus (MCP +
    # Anthropic tool-design docs) is that agents truncate when
    # continuation is only a schema field; an explicit prose hint like
    # "Returned 10 of 133. For 'list every bill' tasks, use one of the
    # find_bills_* aggregate tools instead of paginating." reliably
    # routes the agent to the right next step.
    pagination_hint: str = ""


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
class FacetCoverage:
    """How many bills in a topic actually carry a given data facet.

    The under/overcoverage guard: an agent that knows 'votes' covers
    29/191 bills in ai_governance will say 'no recorded votes' instead
    of hallucinating one, and an agent asked to aggregate over outcomes
    can check the facet is total before trusting the aggregate."""
    facet: str            # 'actions' | 'cosponsors' | 'votes' | 'outcome' | 'subjects' | 'embeddings'
    bills_with_facet: int
    bill_count: int


@dataclass(frozen=True)
class TopicCoverage:
    topic: str
    bill_count: int
    congresses: list[int]
    description: str | None
    facets: list[FacetCoverage]


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
    topics: list[TopicCoverage] = field(default_factory=list)


# ----- passage dynamics subsystem (votes / outcomes) -----

Outcome = Literal[
    "enacted", "vetoed", "failed_passage", "failed_cloture",
    "passed_house_only", "passed_senate_only", "passed_both",
    "died_after_passing_house", "died_after_passing_senate",
    "died_after_passing_both", "reported_no_floor_vote",
    "died_in_committee", "pending",
]

VoteType = Literal["passage", "cloture", "veto_override", "amendment", "procedural"]


@dataclass(frozen=True)
class VoteSummary:
    vote_id: str
    chamber: str                      # 'House' | 'Senate'
    congress: int
    session: int
    roll_number: int
    date: str | None
    question: str | None
    result: str | None
    vote_type: VoteType
    yea_total: int
    nay_total: int
    dem_yea: int | None
    dem_nay: int | None
    rep_yea: int | None
    rep_nay: int | None
    # min over {D,R} of that party's yea-share. None for voice votes /
    # unanimous consent (no roll call) or missing party decomposition.
    bipartisan_support: float | None
    bipartisan_label: str | None      # party_line | cross_party | bipartisan | near_unanimous
    source_url: str


@dataclass(frozen=True)
class OutcomeEvent:
    event: str            # passed_house | passed_senate | failed_cloture | failed_passage | vetoed
    date: str | None
    evidence: str         # verbatim action text or roll-call summary


@dataclass(frozen=True)
class BillVotesResult:
    bill_id: str
    in_scope: bool
    not_found: bool
    outcome: Outcome | None
    public_law: str | None
    bipartisan_support: float | None  # on the final passage-class vote
    cluster: str | None               # secret_congress topic only
    curator_note: str | None
    events: list[OutcomeEvent]
    votes: list[VoteSummary]
    provenance: Provenance


@dataclass(frozen=True)
class CountBucket:
    key: str | int | None
    count: int


@dataclass(frozen=True)
class CountResult:
    """Aggregate counting primitive. One call answers 'how many bills
    ...?' queries that otherwise force an agent to paginate search
    results and count them client-side (the known eval failure mode)."""
    count: int
    group_by: str | None
    buckets: list[CountBucket]
    filters: dict[str, str | int | None]
    provenance: Provenance


@dataclass(frozen=True)
class OutcomeBillSummary:
    bill_id: str
    title: str | None
    topic: str
    congress: int
    outcome: Outcome | None
    public_law: str | None
    bipartisan_support: float | None
    cluster: str | None
    latest_action_date: str | None


@dataclass(frozen=True)
class BillsByOutcomeResult:
    bills: list[OutcomeBillSummary]
    total: int
    filters: dict[str, str | float | int | None]
    provenance: Provenance


# ----- definitions subsystem (PR3) -----

DefinitionType = Literal["direct", "by_reference"]
DefinitionScope = Literal["section_local", "title_local", "bill_local", "statute_global", "jurisdiction_global"]


@dataclass(frozen=True)
class DefinedTerm:
    """A term defined in a specific bill, with its scope and (optional) by-reference target.

    See schema_design.md §3. The `by_reference_target_citation` is set
    when the definition is "has the meaning given such term in
    [USC citation]" — i.e., the bill inherits another statute's
    definition rather than defining the term from scratch. Cross-bill
    consensus / divergence is visible by grouping DefinedTerms with the
    same `surface_form` and comparing definition_type +
    by_reference_target_id.
    """
    defined_term_id: str
    surface_form: str
    bill_id: str                         # the bill (legacy form like '119-hr-1736')
    defining_section_id: str             # legacy form
    defining_section_citation: str       # human-readable, e.g. 'Sec. 3(c)(2) of H.R. 1736, 119th Cong.'
    scope: DefinitionScope
    definition_type: DefinitionType
    definition_text: str
    by_reference_target_id: str | None   # 'statute:us/usc/15/9401' when by_reference + USC
    by_reference_target_citation: str | None  # '15 U.S.C. 9401'
    provenance: Provenance


@dataclass(frozen=True)
class DefinedTermsResult:
    """Response from get_defined_terms(bill_id)."""
    bill_id: str
    terms: list[DefinedTerm]
    coverage_note: str       # e.g. "8 terms across 1 Definitions container"


# ----- amendment subsystem (PR4) -----

AmendmentOperationType = Literal[
    "strike", "insert", "strike_and_insert", "replace",
    "add_at_end", "repeal", "redesignate", "other",
]


@dataclass(frozen=True)
class Amendment:
    """A reified amendment operation. See schema_design.md §4.

    target_text_unverified is True for every operation in v1 — we do not
    yet ingest OLRC USC text, so we cannot verify before_text against the
    statute as it stands today. The synthesis function (Q5 in the doc)
    will emit ConflictNote markers rather than picking a winner when
    verification ultimately runs.
    """
    amendment_id: str
    source_section_id: str              # the bill section issuing the operation (legacy form)
    source_section_citation: str        # 'Sec. 4 of H.R. 8516, 119th Cong.'
    operation_type: AmendmentOperationType
    operation_text: str                 # the prose surrounding the operation, ≤500 chars
    target_statute_section_id: str | None      # 'statute:us/usc/15/9401' when resolved
    target_canonical_citation: str | None      # '15 U.S.C. 9401'
    target_locator_json: str            # structured locator (code, title, section, subdivisions)
    before_text: str | None             # captured from "by striking '...'" patterns
    after_text: str                     # verbatim quoted-block contents (≤4000 chars)
    target_text_unverified: bool        # True in v1 (USC not ingested)
    provenance: Provenance


@dataclass(frozen=True)
class AmendmentsResult:
    """Response from get_amendments(bill_id)."""
    bill_id: str
    amendments: list[Amendment]
    coverage_note: str


@dataclass(frozen=True)
class AmendmentsTargetingResult:
    """Response from get_amendments_targeting(statute_section_id)."""
    statute_section_id: str
    statute_canonical: str
    amendments: list[Amendment]
    coverage_note: str


# ----- aggregate primitives (post-eval-review) -----
#
# These tools collapse N+1 patterns into single Cypher queries. Each one
# answers a "find every X matching Y" question that previously required
# the agent to search_corpus then loop get_defined_terms / get_amendments
# over every hit. See schema_design.md §7 query patterns; the underlying
# graph already knows the answer — these surface it in one call.


@dataclass(frozen=True)
class BillDefinitionMatch:
    """One row of `find_bills_defining`. Each match is a (bill, term)
    pair; a bill that defines the term in multiple sections returns
    multiple rows, one per defining section."""
    bill_id: str                          # legacy form '118-hr-6881'
    bill_short_title: str | None
    bill_title: str
    congress: int
    surface_form: str                     # exact form as it appears in the bill
    defining_section_id: str
    defining_section_citation: str        # 'Sec. 2(d)(4) of H.R. 7913, 118th Cong.'
    definition_type: DefinitionType
    by_reference_target_id: str | None    # 'statute:us/usc/15/9401'
    by_reference_target_citation: str | None  # '15 U.S.C. 9401'


@dataclass(frozen=True)
class BillsDefiningResult:
    """Response from find_bills_defining."""
    term: str
    matches: list[BillDefinitionMatch]
    total: int
    coverage_note: str                    # describes filters applied + scope


@dataclass(frozen=True)
class BillAmendmentSummary:
    """One row of `find_bills_amending`. Compact per-bill rollup of
    amendment operations targeting a given USC section."""
    bill_id: str
    bill_short_title: str | None
    bill_title: str
    congress: int
    n_operations: int                     # count of AmendmentOperations targeting this statute
    operation_types: list[AmendmentOperationType]  # distinct ops, e.g. ['insert', 'add_at_end']


@dataclass(frozen=True)
class BillsAmendingResult:
    """Response from find_bills_amending."""
    statute_section_id: str
    statute_canonical: str
    bills: list[BillAmendmentSummary]
    total: int
    coverage_note: str


@dataclass(frozen=True)
class DefinitionAcrossCorpus:
    """One row of `find_definitions_of` — every bill's take on a term,
    with the bits an agent needs to compare definitions side by side."""
    bill_id: str
    bill_short_title: str | None
    congress: int
    defining_section_citation: str
    definition_type: DefinitionType
    definition_text: str                  # verbatim
    by_reference_target_citation: str | None


@dataclass(frozen=True)
class DefinitionsAcrossCorpusResult:
    """Response from find_definitions_of."""
    term: str
    definitions: list[DefinitionAcrossCorpus]
    total: int
    direct_count: int
    by_reference_count: int
    coverage_note: str


# ----- universe layer (all bills of covered Congresses, status-only) -----

@dataclass(frozen=True)
class BillNameMatch:
    bill_id: str
    title: str | None
    congress: int
    bill_type: str
    bill_number: int
    outcome: Outcome | None
    public_law: str | None
    in_corpus: bool          # full text available via get_bill/get_section
    match_kind: str          # 'bill_id' | 'alias_exact' | 'fts'
    matched_alias: str | None


@dataclass(frozen=True)
class BillLookupResult:
    """Resolution of a colloquial bill name ('CHIPS Act', 'the border
    bill') or a bill id to canonical bill_id(s)."""
    query: str
    matches: list[BillNameMatch]
    is_ambiguous: bool
    provenance: Provenance


@dataclass(frozen=True)
class UniverseBillSummary:
    bill_id: str
    title: str | None
    congress: int
    outcome: Outcome | None
    public_law: str | None
    policy_area: str | None
    sponsor_party: str | None
    sponsor_state: str | None
    bipartisan_support: float | None
    in_corpus: bool
    latest_action_date: str | None


@dataclass(frozen=True)
class UniverseBillsResult:
    bills: list[UniverseBillSummary]
    total: int
    filters: dict[str, str | float | int | None]
    provenance: Provenance


@dataclass(frozen=True)
class BillCard:
    """One-call context card for any bill in the universe. Collapses the
    get_bill + get_bill_votes + coverage-check round trips into a single
    tool call; corpus-only structure counts (sections, defined terms,
    amendments) are included when available so the agent knows whether
    drill-down tools will work BEFORE calling them."""
    bill_id: str
    found: bool
    in_corpus: bool
    topic: str | None              # corpus topic when in_corpus
    title: str | None
    all_known_names: list[str]
    congress: int | None
    bill_type: str | None
    bill_number: int | None
    sponsor: str | None
    sponsor_party: str | None
    sponsor_state: str | None
    policy_area: str | None
    introduced_date: str | None
    latest_action: str | None
    outcome: Outcome | None
    public_law: str | None
    bipartisan_support: float | None
    bipartisan_label: str | None
    cosponsor_counts: dict[str, int]
    cluster: str | None
    curator_note: str | None
    events: list[OutcomeEvent]
    votes: list[VoteSummary]
    section_count: int | None      # None = unknown (not in corpus)
    defined_term_count: int | None
    amendment_count: int | None
    provenance: Provenance
