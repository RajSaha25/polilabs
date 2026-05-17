"""Candidate bill data shape and centrality scoring.

A Candidate is a deduplicated unique bill (one per congress+type+number) with
metadata reconciled from GovInfo and Congress.gov, plus a centrality score
that ranks how likely it is to be a Tier-A AI-governance bill.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Any

# Anchor keywords (REQUIRED — at least one must appear, per inclusion_criteria.md)
ANCHORS: list[str] = [
    "artificial intelligence",
    "machine learning",
    # "AI" handled separately as a word-boundary match
]

# Additional in-scope terms — expand relevance signal when present
EXTRA_TERMS: list[str] = [
    "facial recognition",
    "generative ai",
    "generative artificial intelligence",
    "frontier model",
    "automated decision systems",
    "automated decision system",
]

# Excluded — present in criteria for clarity, not used in matching
EXCLUDED_STANDALONE: list[str] = [
    "algorithmic decision making",
]

# In-scope bill types per criteria v1.0 (excludes simple resolutions hres/sres)
IN_SCOPE_TYPES = {"hr", "s", "hjres", "sjres", "hconres", "sconres"}

# Bills whose only AI signal is "AI" standalone (not "artificial intelligence")
_AI_TOKEN_RE = re.compile(r"\bAI\b")  # case-sensitive — uppercase formal acronym
_PACKAGE_ID_RE = re.compile(r"^BILLS-(\d{3})(hr|s|hjres|sjres|hconres|sconres|hres|sres)(\d+)([a-z]+)$")


@dataclass(frozen=True)
class PackageRef:
    """One bill version on GovInfo."""
    package_id: str
    version_code: str       # e.g. 'ih', 'es', 'enr'
    date_issued: str        # ISO date
    title: str

    @property
    def bill_id(self) -> str:
        m = _PACKAGE_ID_RE.match(self.package_id)
        if not m:
            raise ValueError(f"unparseable package id: {self.package_id}")
        congress, bill_type, number, _ = m.groups()
        return f"{congress}-{bill_type}-{number}"


def parse_package_id(package_id: str) -> tuple[int, str, int, str] | None:
    """Parse BILLS-{congress}{type}{number}{version} → (congress, type, number, version)."""
    m = _PACKAGE_ID_RE.match(package_id)
    if not m:
        return None
    congress, bill_type, number, version = m.groups()
    return int(congress), bill_type, int(number), version


@dataclass
class Candidate:
    """Deduplicated unique bill with reconciled metadata and scoring."""
    # Identity
    bill_id: str            # e.g. "118-hr-5949"
    congress: int
    bill_type: str
    bill_number: int

    # GovInfo data
    versions: list[PackageRef] = field(default_factory=list)
    govinfo_titles: list[str] = field(default_factory=list)

    # Congress.gov metadata (filled by reconciliation step)
    congress_gov_title: str | None = None
    short_title: str | None = None
    sponsor: str | None = None
    introduced_date: str | None = None
    latest_action: str | None = None
    policy_area: str | None = None
    subjects: list[str] = field(default_factory=list)
    summary_text: str | None = None  # latest summary from Congress.gov

    # Scoring
    centrality_score: float = 0.0
    match_locations: dict[str, list[str]] = field(default_factory=dict)
    has_anchor: bool = False  # criteria gate: must be True to include
    proposed_tier: str | None = None  # "A" or "B"; reviewer overrides

    # Errors / notes
    reconciliation_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _haystacks(c: Candidate) -> dict[str, str]:
    """Map of location → searchable text. Location key drives centrality weighting."""
    return {
        "title": (c.congress_gov_title or "").lower(),
        "short_title": (c.short_title or "").lower(),
        "policy_area": (c.policy_area or "").lower(),
        "subjects": " ".join(c.subjects).lower(),
        "summary": (c.summary_text or "").lower(),
    }


# Centrality weights — higher means more likely Tier A
_LOC_WEIGHT = {
    "title": 4.0,
    "short_title": 3.0,
    "policy_area": 2.5,
    "subjects": 2.0,
    "summary": 1.0,
}


def score_centrality(c: Candidate) -> None:
    """Compute centrality score and match_locations on the Candidate in place.

    Anchor gate: a Candidate has_anchor=True iff at least one of
    {artificial intelligence, machine learning, AI-as-standalone-word} appears
    in title, short_title, policy_area, subjects, summary, OR govinfo title.

    Score: sum over locations of (weight × number of distinct anchor/extra terms hit there).
    """
    hays = _haystacks(c)
    # Also check GovInfo title text in case Congress.gov metadata is incomplete
    govinfo_title_lc = " ".join(c.govinfo_titles).lower()

    match_locations: dict[str, list[str]] = {}
    anchor_hit = False
    score = 0.0

    for loc, text in hays.items():
        loc_hits: list[str] = []
        # Anchor terms (lowercase phrase match)
        for anchor in ANCHORS:
            if anchor in text:
                loc_hits.append(anchor)
                anchor_hit = True
        # "AI" standalone: check against ORIGINAL-case version since we want uppercase
        original_text = {
            "title": c.congress_gov_title or "",
            "short_title": c.short_title or "",
            "policy_area": c.policy_area or "",
            "subjects": " ".join(c.subjects),
            "summary": c.summary_text or "",
        }[loc]
        if _AI_TOKEN_RE.search(original_text):
            loc_hits.append("AI")
            anchor_hit = True
        # Extra terms
        for extra in EXTRA_TERMS:
            if extra in text:
                loc_hits.append(extra)
        if loc_hits:
            match_locations[loc] = loc_hits
            score += _LOC_WEIGHT[loc] * len(set(loc_hits))

    # Fallback: anchor present in GovInfo title only
    if not anchor_hit:
        for anchor in ANCHORS:
            if anchor in govinfo_title_lc:
                anchor_hit = True
                match_locations.setdefault("govinfo_title", []).append(anchor)
                score += _LOC_WEIGHT["title"] * 0.5  # discount: GovInfo title can be generic
        for raw in c.govinfo_titles:
            if _AI_TOKEN_RE.search(raw):
                anchor_hit = True
                match_locations.setdefault("govinfo_title", []).append("AI")
                score += _LOC_WEIGHT["title"] * 0.5

    c.has_anchor = anchor_hit
    c.centrality_score = round(score, 3)
    c.match_locations = match_locations

    # Tier suggestion: A if anchor in title/short_title; otherwise B
    if "title" in match_locations or "short_title" in match_locations:
        # If primary location is title, lean A. Heuristic only.
        if any(a in match_locations.get("title", []) or a in match_locations.get("short_title", []) for a in ANCHORS + ["AI"]):
            c.proposed_tier = "A"
        else:
            c.proposed_tier = "B"
    else:
        c.proposed_tier = "B"
