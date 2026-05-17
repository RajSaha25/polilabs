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
    centrality_score        REAL,
    canonical_package_id    TEXT,
    canonical_version_code  TEXT,
    canonical_version_date  TEXT,
    xml_format              TEXT,        -- 'uslm' | 'pre-uslm'
    UNIQUE (congress, bill_type, bill_number)
);

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

CREATE TABLE IF NOT EXISTS corpus_meta (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_freshness (
    source        TEXT PRIMARY KEY,    -- 'congress.gov' | 'govinfo' | 'olrc'
    last_fetched  TEXT NOT NULL
);

-- FTS5 over bill-level metadata
CREATE VIRTUAL TABLE IF NOT EXISTS bills_fts USING fts5(
    bill_id      UNINDEXED,
    title,
    short_title,
    summary_text,
    policy_area,
    sponsor,
    tokenize='porter unicode61'
);

-- FTS5 over section text — enables body-text search
CREATE VIRTUAL TABLE IF NOT EXISTS sections_fts USING fts5(
    section_id  UNINDEXED,
    bill_id     UNINDEXED,
    heading,
    text_full,
    tokenize='porter unicode61'
);
"""
