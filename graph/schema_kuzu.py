"""Kùzu schema for the polilabs property graph.

See schema_design.md (committed to repo root) for the design contract this
implements. PR1 scope: bibliographic spine (Bill, BillVersion, Section,
Sponsor, Jurisdiction) plus the provenance plumbing (Extractor,
ProvenanceRecord).

Node and rel tables for the substantive-law family (Statute,
StatuteSection), the definitions family (DefinedTerm, UnresolvedTermUse),
and the amendment/interpretive families are declared up front so the
schema is stable across PRs. They are populated in later PRs.

The schema is destructive: scripts/build_kuzu_index.py drops the DB and
recreates it from data/corpus/, which is the source of truth.
"""
from __future__ import annotations

# Each statement runs separately via conn.execute(). Order matters: node
# tables must exist before rel tables that reference them. Rel tables are
# declared even when unpopulated so that downstream code can issue MATCH
# queries against them without schema-not-found errors.

NODE_TABLES = [
    # ----- bibliographic family -----
    """CREATE NODE TABLE Jurisdiction(
        urn STRING,
        name STRING,
        legal_system STRING,
        PRIMARY KEY(urn)
    )""",

    """CREATE NODE TABLE Bill(
        bill_id STRING,
        congress INT64,
        bill_type STRING,
        bill_number INT64,
        jurisdiction_urn STRING,
        official_title STRING,
        short_title STRING,
        primary_subject STRING,
        summary_text STRING,
        current_status STRING,
        latest_action_date DATE,
        latest_action_text STRING,
        tier STRING,
        stream STRING,
        centrality_score DOUBLE,
        sponsor_display_name STRING,
        PRIMARY KEY(bill_id)
    )""",

    """CREATE NODE TABLE BillVersion(
        version_id STRING,
        bill_id STRING,
        stage STRING,
        version_observed_at DATE,
        knowledge_recorded_at TIMESTAMP,
        xml_format STRING,
        source_package_id STRING,
        is_current BOOLEAN,
        PRIMARY KEY(version_id)
    )""",

    """CREATE NODE TABLE Section(
        section_id STRING,
        version_id STRING,
        level STRING,
        enum STRING,
        heading STRING,
        text_self STRING,
        text_full STRING,
        canonical_citation STRING,
        ordinal INT64,
        xml_id STRING,
        PRIMARY KEY(section_id)
    )""",

    """CREATE NODE TABLE Sponsor(
        sponsor_id STRING,
        bioguide_id STRING,
        display_name STRING,
        first_name STRING,
        last_name STRING,
        party STRING,
        state STRING,
        district STRING,
        id_source STRING,
        PRIMARY KEY(sponsor_id)
    )""",

    """CREATE NODE TABLE Committee(
        committee_key STRING,
        congress INT64,
        chamber STRING,
        system_code STRING,
        name STRING,
        PRIMARY KEY(committee_key)
    )""",

    # ----- substantive-law family (declared; populated in later PRs) -----
    """CREATE NODE TABLE Statute(
        statute_id STRING,
        code STRING,
        title STRING,
        section STRING,
        popular_name STRING,
        PRIMARY KEY(statute_id)
    )""",

    """CREATE NODE TABLE StatuteSection(
        statute_section_id STRING,
        statute_id STRING,
        enum_path STRING,
        canonical_citation STRING,
        PRIMARY KEY(statute_section_id)
    )""",

    # ----- definitions family (declared; populated in PR3) -----
    """CREATE NODE TABLE DefinedTerm(
        defined_term_id STRING,
        surface_form STRING,
        defining_section_id STRING,
        scope STRING,
        definition_text STRING,
        definition_type STRING,
        by_reference_target_id STRING,
        PRIMARY KEY(defined_term_id)
    )""",

    """CREATE NODE TABLE UnresolvedTermUse(
        unresolved_id STRING,
        section_id STRING,
        surface_form STRING,
        reason STRING,
        PRIMARY KEY(unresolved_id)
    )""",

    # ----- amendment family (declared; populated in PR4) -----
    """CREATE NODE TABLE AmendmentOperation(
        amendment_id STRING,
        source_section_id STRING,
        operation_type STRING,
        target_locator_json STRING,
        before_text STRING,
        after_text STRING,
        effective_date DATE,
        target_text_unverified BOOLEAN,
        PRIMARY KEY(amendment_id)
    )""",

    # ----- provenance plumbing -----
    """CREATE NODE TABLE Extractor(
        extractor_id STRING,
        version STRING,
        kind STRING,
        PRIMARY KEY(extractor_id)
    )""",

    """CREATE NODE TABLE ProvenanceRecord(
        provenance_id STRING,
        extractor_id STRING,
        model_id STRING,
        prompt_template_hash STRING,
        input_hash STRING,
        derived_at TIMESTAMP,
        verified_by STRING,
        verified_at TIMESTAMP,
        verification_method STRING,
        confidence DOUBLE,
        PRIMARY KEY(provenance_id)
    )""",
]

REL_TABLES = [
    # ----- bibliographic edges (populated in PR1) -----
    "CREATE REL TABLE OF_JURISDICTION(FROM Bill TO Jurisdiction)",
    "CREATE REL TABLE HAS_VERSION(FROM Bill TO BillVersion, is_current BOOLEAN)",
    "CREATE REL TABLE HAS_SECTION(FROM BillVersion TO Section, ordinal INT64)",
    "CREATE REL TABLE PARENT_OF(FROM Section TO Section, ordinal INT64)",
    "CREATE REL TABLE SPONSORED_BY(FROM Bill TO Sponsor, sponsorship_date DATE)",
    """CREATE REL TABLE COSPONSORED_BY(
        FROM Bill TO Sponsor,
        sponsorship_date DATE,
        is_original BOOLEAN
    )""",
    "CREATE REL TABLE REFERRED_TO(FROM Bill TO Committee, referral_date DATE)",

    # ----- citation edges (declared; populated in PR2) -----
    """CREATE REL TABLE CITES_EXTERNAL(
        FROM Section TO StatuteSection,
        raw_text STRING,
        xml_ref_id STRING,
        derivation STRING,
        confidence DOUBLE,
        provenance_id STRING
    )""",
    """CREATE REL TABLE CITES_INTERNAL(
        FROM Section TO Section,
        raw_text STRING,
        xml_ref_id STRING,
        derivation STRING,
        confidence DOUBLE,
        provenance_id STRING
    )""",

    # ----- definitions edges (declared; populated in PR3) -----
    """CREATE REL TABLE DEFINES(
        FROM Section TO DefinedTerm,
        definition_type STRING
    )""",
    """CREATE REL TABLE RESOLVED_TO(
        FROM Section TO DefinedTerm,
        char_offset INT64,
        confidence DOUBLE,
        derivation STRING
    )""",
    "CREATE REL TABLE UNRESOLVED_USE_IN(FROM UnresolvedTermUse TO Section, surface_form STRING)",
    """CREATE REL TABLE BY_REFERENCE(
        FROM DefinedTerm TO StatuteSection,
        confidence DOUBLE
    )""",

    # ----- amendment edges (declared; populated in PR4) -----
    "CREATE REL TABLE AMENDS(FROM Section TO AmendmentOperation, xml_ref_id STRING)",
    "CREATE REL TABLE TARGETS(FROM AmendmentOperation TO StatuteSection, enum_path_in_target STRING)",

    # ----- provenance backbone -----
    "CREATE REL TABLE PRODUCED(FROM Extractor TO ProvenanceRecord)",
]


def apply_schema(conn) -> None:
    """Run all DDL statements on a fresh Kùzu connection.

    Caller is responsible for opening on a clean DB directory — Kùzu does
    not gracefully tolerate re-creating an existing table.
    """
    for stmt in NODE_TABLES + REL_TABLES:
        conn.execute(stmt)
