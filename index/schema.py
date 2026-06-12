"""SQLite schema for the polilabs Layer-2 index.

Driven by what the api/SPEC.md primitives need to return:
- stable opaque IDs (bill_id, section_id)
- typed citation edges
- hierarchical sections with parent pointers
- per-record provenance fields
- FTS5 search over bills and sections

Note: the citations table is created empty in v1. Citation extraction is
deferred to Phase 4 (cross-source verification); get_citation_graph and
resolve_citation operate on whatever is in this table, returning empty
results with a provenance note when nothing matches.
"""
from __future__ import annotations

SCHEMA = r"""
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS bills (
    bill_id                 TEXT PRIMARY KEY,
    congress                INTEGER NOT NULL,
    bill_type               TEXT NOT NULL,
    bill_number             INTEGER NOT NULL,
    title                   TEXT,
    short_title             TEXT,
    sponsor                 TEXT,
    introduced_date         TEXT,
    latest_action_date      TEXT,
    latest_action_text      TEXT,
    policy_area             TEXT,
    summary_text            TEXT,
    tier                    TEXT,
    stream                  TEXT NOT NULL DEFAULT 'legislation',
    -- Policy domain. Orthogonal to `stream`: stream is the source-class
    -- (legislation vs. rule vs. guidance); topic is the subject-matter
    -- corpus (ai_governance vs. redistricting vs. ...).
    topic                   TEXT NOT NULL DEFAULT 'ai_governance',
    centrality_score        REAL,
    canonical_package_id    TEXT,
    canonical_version_code  TEXT,
    canonical_version_date  TEXT,
    xml_format              TEXT,        -- 'uslm' | 'pre-uslm'
    -- Passage-dynamics fields, populated from billstatus.json when the
    -- bill dir has one (see ingest/billstatus.py). NULL = not enriched,
    -- which is distinct from 'pending' (enriched, still alive).
    outcome                 TEXT,        -- enacted | vetoed | failed_passage |
                                         -- failed_cloture | died_in_committee |
                                         -- reported_no_floor_vote | pending |
                                         -- passed_{house,senate}_only | passed_both |
                                         -- died_after_passing_{house,senate,both}
    public_law              TEXT,        -- 'PL 117-167' when enacted
    -- min over {D,R} of that party's yea-share on the final passage-class
    -- vote; NULL when the bill never had a partisan-decomposable roll call
    -- (voice votes, unanimous consent, died in committee).
    bipartisan_support      REAL,
    -- Curated passage-dynamics cluster (secret_congress topic only);
    -- vocabulary in corpus/secret_congress_criteria.md.
    cluster                 TEXT,
    curator_note            TEXT,
    -- JSON list of {event, date, evidence} rows from billstatus.json:
    -- the dated record behind `outcome` (passed_house, failed_cloture,
    -- ...), so "why did it fail?" answers carry evidence.
    outcome_events          TEXT,
    UNIQUE (congress, bill_type, bill_number)
);
CREATE INDEX IF NOT EXISTS idx_bills_topic ON bills(topic);
CREATE INDEX IF NOT EXISTS idx_bills_outcome ON bills(outcome);

CREATE TABLE IF NOT EXISTS bill_versions (
    package_id    TEXT PRIMARY KEY,
    bill_id       TEXT NOT NULL REFERENCES bills(bill_id) ON DELETE CASCADE,
    version_code  TEXT NOT NULL,
    date_issued   TEXT
);

CREATE TABLE IF NOT EXISTS sections (
    section_id            TEXT PRIMARY KEY,
    bill_id               TEXT NOT NULL REFERENCES bills(bill_id) ON DELETE CASCADE,
    parent_section_id     TEXT REFERENCES sections(section_id) ON DELETE CASCADE,
    level                 TEXT NOT NULL,     -- section, subsection, paragraph, etc.
    enum                  TEXT,              -- '1.', '(a)', '(2)', etc.
    heading               TEXT,
    text_self             TEXT,              -- direct text content of this element
    text_full             TEXT,              -- recursive text incl. all descendants
    canonical_citation    TEXT NOT NULL,
    ordinal               INTEGER NOT NULL,  -- order within parent
    xml_id                TEXT
);

CREATE INDEX IF NOT EXISTS idx_sections_bill ON sections(bill_id);
CREATE INDEX IF NOT EXISTS idx_sections_parent ON sections(parent_section_id);

CREATE TABLE IF NOT EXISTS cosponsors (
    bill_id          TEXT NOT NULL REFERENCES bills(bill_id) ON DELETE CASCADE,
    name             TEXT NOT NULL,
    party            TEXT,
    state            TEXT,
    sponsorship_date TEXT,
    PRIMARY KEY (bill_id, name)
);

CREATE TABLE IF NOT EXISTS actions (
    bill_id      TEXT NOT NULL REFERENCES bills(bill_id) ON DELETE CASCADE,
    ordinal      INTEGER NOT NULL,
    action_date  TEXT,
    action_text  TEXT,
    PRIMARY KEY (bill_id, ordinal)
);

CREATE TABLE IF NOT EXISTS subjects (
    bill_id  TEXT NOT NULL REFERENCES bills(bill_id) ON DELETE CASCADE,
    subject  TEXT NOT NULL,
    PRIMARY KEY (bill_id, subject)
);

-- Roll-call votes, from billstatus.json (ingest/billstatus.py). One row
-- per recorded vote on the bill, both chambers, including votes from a
-- bill's earlier life under another name (vehicle bills).
CREATE TABLE IF NOT EXISTS votes (
    vote_id            TEXT PRIMARY KEY,   -- '{bill_id}::{chamber}/{congress}-{session}/{roll}'
    bill_id            TEXT NOT NULL REFERENCES bills(bill_id) ON DELETE CASCADE,
    chamber            TEXT NOT NULL,      -- 'House' | 'Senate'
    congress           INTEGER NOT NULL,
    session            INTEGER NOT NULL,
    roll_number        INTEGER NOT NULL,
    date               TEXT,
    question           TEXT,
    result             TEXT,
    vote_type          TEXT NOT NULL,      -- passage | cloture | veto_override | amendment | procedural
    yea_total          INTEGER NOT NULL,
    nay_total          INTEGER NOT NULL,
    dem_yea            INTEGER, dem_nay  INTEGER,
    rep_yea            INTEGER, rep_nay  INTEGER,
    ind_yea            INTEGER, ind_nay  INTEGER,
    bipartisan_support REAL,               -- min major-party yea-share; see ingest/billstatus.py
    bipartisan_label   TEXT,               -- party_line | cross_party | bipartisan | near_unanimous
    source_url         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_votes_bill ON votes(bill_id);
CREATE INDEX IF NOT EXISTS idx_votes_type ON votes(vote_type);

-- Per-member positions for outcome-determining votes only (passage,
-- cloture, veto override). Party totals in `votes` cover the rest.
-- Enables geography questions: "how did the California delegation vote
-- on CHIPS?"
CREATE TABLE IF NOT EXISTS vote_positions (
    vote_id      TEXT NOT NULL REFERENCES votes(vote_id) ON DELETE CASCADE,
    member_name  TEXT NOT NULL,
    member_id    TEXT,               -- bioguide (House) or LIS id (Senate)
    party        TEXT,
    state        TEXT,
    position     TEXT NOT NULL,      -- yea | nay | present | not_voting | other
    PRIMARY KEY (vote_id, member_name)
);
CREATE INDEX IF NOT EXISTS idx_vote_positions_state ON vote_positions(state);

-- Reserved for Phase 4 citation extraction. Empty in v1.
CREATE TABLE IF NOT EXISTS citations (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    source_section_id  TEXT NOT NULL REFERENCES sections(section_id) ON DELETE CASCADE,
    target_section_id  TEXT,    -- nullable: external citations have only a string ref
    target_external    TEXT,    -- e.g. '42 U.S.C. § 1983' for citations outside the corpus
    type               TEXT NOT NULL CHECK(type IN ('amends','repeals','cites','references'))
);
CREATE UNIQUE INDEX IF NOT EXISTS uniq_citations
    ON citations(source_section_id, IFNULL(target_section_id, ''), IFNULL(target_external, ''), type);
CREATE INDEX IF NOT EXISTS idx_citations_target ON citations(target_section_id);

-- ---------------------------------------------------------------------
-- UNIVERSE layer: one lightweight status record for EVERY law-track bill
-- (hr, s, hjres, sjres) of the covered Congresses, built from GovInfo
-- BILLSTATUS bulk data (scripts/build_universe.py). No full text — the
-- curated topic corpora carry text; the universe carries facts. This is
-- what lets the agent answer "did H.R. X pass?" for any federal bill
-- and gives corpus-level claims a denominator.
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS universe_bills (
    bill_id            TEXT PRIMARY KEY,
    congress           INTEGER NOT NULL,
    bill_type          TEXT NOT NULL,
    bill_number        INTEGER NOT NULL,
    title              TEXT,
    introduced_date    TEXT,
    origin_chamber     TEXT,
    policy_area        TEXT,
    sponsor_name       TEXT,
    sponsor_party      TEXT,
    sponsor_state      TEXT,
    sponsor_bioguide   TEXT,
    cosponsors_d       INTEGER NOT NULL DEFAULT 0,
    cosponsors_r       INTEGER NOT NULL DEFAULT 0,
    cosponsors_i       INTEGER NOT NULL DEFAULT 0,
    cosponsors_total   INTEGER NOT NULL DEFAULT 0,
    latest_action_date TEXT,
    latest_action_text TEXT,
    outcome            TEXT,
    public_law         TEXT,
    outcome_events     TEXT,   -- JSON list, capped
    vote_refs          TEXT,   -- JSON list of recorded-vote pointers
    -- final passage-class roll-call metrics; NULL until the roll-call
    -- enrichment pass (scripts/fetch_universe_rollcalls.py) runs
    bipartisan_support REAL,
    bipartisan_label   TEXT,
    in_corpus          INTEGER NOT NULL DEFAULT 0,  -- full text in a topic corpus
    UNIQUE (congress, bill_type, bill_number)
);
CREATE INDEX IF NOT EXISTS idx_universe_outcome  ON universe_bills(outcome);
CREATE INDEX IF NOT EXISTS idx_universe_congress ON universe_bills(congress);
CREATE INDEX IF NOT EXISTS idx_universe_policy   ON universe_bills(policy_area);

-- Party-split roll calls for universe bills (totals only, no members).
CREATE TABLE IF NOT EXISTS universe_votes (
    vote_id            TEXT PRIMARY KEY,
    bill_id            TEXT NOT NULL REFERENCES universe_bills(bill_id) ON DELETE CASCADE,
    chamber            TEXT NOT NULL,
    congress           INTEGER NOT NULL,
    session            INTEGER NOT NULL,
    roll_number        INTEGER NOT NULL,
    date               TEXT,
    question           TEXT,
    result             TEXT,
    vote_type          TEXT NOT NULL,
    yea_total          INTEGER NOT NULL,
    nay_total          INTEGER NOT NULL,
    dem_yea            INTEGER, dem_nay INTEGER,
    rep_yea            INTEGER, rep_nay INTEGER,
    bipartisan_support REAL,
    bipartisan_label   TEXT,
    source_url         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_universe_votes_bill ON universe_votes(bill_id);

-- Alias / popular-name resolution: every title variant BILLSTATUS knows
-- (short titles per stage, popular titles, display titles), normalized.
-- The entry point for "CHIPS Act" -> 117-hr-4346. Covers the whole
-- universe, so curated-corpus membership is irrelevant to name lookup.
CREATE TABLE IF NOT EXISTS bill_aliases (
    alias_norm TEXT NOT NULL,    -- lowercased, punctuation-stripped, 'of YYYY' dropped
    alias      TEXT NOT NULL,    -- original surface form
    bill_id    TEXT NOT NULL,
    source     TEXT NOT NULL,    -- 'billstatus_titles'
    PRIMARY KEY (alias_norm, bill_id)
);
CREATE INDEX IF NOT EXISTS idx_aliases_norm ON bill_aliases(alias_norm);

-- FTS over universe titles + aliases for fuzzy name lookup when exact
-- normalized match fails.
CREATE VIRTUAL TABLE IF NOT EXISTS universe_fts USING fts5(
    bill_id  UNINDEXED,
    title,
    aliases,
    summary,
    tokenize='porter unicode61'
);

-- Latest CRS-written summary per bill (GovInfo BILLSUM bulk data).
-- CRS revises at each major action, so this reflects the bill's final
-- state. Coverage is near-total for closed Congresses and lags for the
-- current one — corpus_coverage() reports the exact facet numbers.
CREATE TABLE IF NOT EXISTS universe_summaries (
    bill_id      TEXT PRIMARY KEY REFERENCES universe_bills(bill_id) ON DELETE CASCADE,
    action_desc  TEXT,    -- e.g. 'Public Law', 'Introduced in House'
    action_date  TEXT,
    update_date  TEXT,
    summary_text TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS corpus_meta (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_freshness (
    source        TEXT PRIMARY KEY,    -- 'congress.gov' | 'govinfo' | 'olrc'
    last_fetched  TEXT NOT NULL
);

-- FTS5 over bill-level metadata. `topic` carried as UNINDEXED so callers
-- can `... MATCH ? AND topic = ?` cheaply at query time without polluting
-- the BM25 score.
CREATE VIRTUAL TABLE IF NOT EXISTS bills_fts USING fts5(
    bill_id      UNINDEXED,
    topic        UNINDEXED,
    title,
    short_title,
    summary_text,
    policy_area,
    sponsor,
    tokenize='porter unicode61'
);

-- FTS5 over section text — enables body-text search. `topic` propagated
-- from the parent bill for the same query-time filter pattern.
CREATE VIRTUAL TABLE IF NOT EXISTS sections_fts USING fts5(
    section_id  UNINDEXED,
    bill_id     UNINDEXED,
    topic       UNINDEXED,
    heading,
    text_full,
    tokenize='porter unicode61'
);

-- Dense embeddings over section text — the dense leg of hybrid search.
-- The embedding column stores raw float32 bytes (numpy .tobytes()), which
-- is the cheapest format that round-trips fast through Python. At
-- bge-small dim=384 that's 1,536 bytes per row; ~43k sections → ~66 MB.
-- A vector-search SQLite extension is overkill at this scale — query
-- time does an in-Python cosine sweep, gated by topic + bill filters.
CREATE TABLE IF NOT EXISTS section_embeddings (
    section_id     TEXT PRIMARY KEY REFERENCES sections(section_id) ON DELETE CASCADE,
    bill_id        TEXT NOT NULL REFERENCES bills(bill_id) ON DELETE CASCADE,
    topic          TEXT NOT NULL,
    embedding      BLOB NOT NULL,
    model_version  TEXT NOT NULL,
    dim            INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_section_embeddings_topic ON section_embeddings(topic);
CREATE INDEX IF NOT EXISTS idx_section_embeddings_bill  ON section_embeddings(bill_id);
"""
