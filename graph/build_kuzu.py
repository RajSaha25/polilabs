"""Build the polilabs Kùzu graph from data/corpus/legislation/.

Two-phase build:

  Phase 1 (collect): walk every bill directory, parse metadata + XML, and
  accumulate rows into per-table Python lists. No DB writes here.

  Phase 2 (bulk insert): one UNWIND-based query per node table and per
  rel table, chunked for memory bounds. UNWIND batches 1000s of rows per
  Cypher round-trip; one-CREATE-per-row was ~15 min for this corpus, the
  batched version takes ~10–30s.

Destructive: deletes any existing DB at the target path. The Kùzu store
is regenerable from data/corpus/, which is the source of truth.

Populated through PR4:
  - PR1: bibliographic spine (Bill, BillVersion, Section, Sponsor, etc.)
  - PR2: CITES_EXTERNAL (USC) + StatuteSection lazy-MERGE
  - PR3: DefinedTerm + DEFINES (Section→DefinedTerm) + BY_REFERENCE
         (DefinedTerm→StatuteSection)
  - PR4: AmendmentOperation reified nodes + AMENDS (Section→Op) +
         TARGETS (Op→StatuteSection). All operations carry
         target_text_unverified=true until OLRC USC ingestion.

Out of scope (populates in later PRs):
  - RESOLVED_TO + UnresolvedTermUse use-site resolution (PR3.1)
  - CITES_INTERNAL (PR2.1 — needs USLM <ref href> parsing)
  - StatuteVersion ingestion from OLRC (deferred per design decision)
  - Committee / REFERRED_TO extraction (deferred to a follow-up)
  - Public Law citations (74 in corpus; need a PublicLaw node type)

Honesty notes:
  - Primary sponsors lack bioguide IDs in metadata.json; we mint
    `_legacy:` IDs tagged id_source='fallback' so a later
    Congress.gov reconciliation pass can swap them.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import kuzu

# Reuse the existing XML parser — handles both USLM and pre-USLM dialects.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from index.parse_uslm import parse_bill_xml  # noqa: E402

from .extract_citations import (  # noqa: E402
    ExternalCitation,
    extract_external_citations,
)
from .extract_amendments import (  # noqa: E402
    AmendmentRow,
    extract_amendments,
)
from .extract_definitions import (  # noqa: E402
    DefinedTermRow,
    extract_defined_terms,
)
from .schema_kuzu import apply_schema  # noqa: E402

CORPUS_DIR = Path("data/corpus/legislation")  # legacy AI corpus (back-compat)
CORPUS_BASE = Path("data/corpus")             # parent of all topic subdirs
GRAPH_PATH = Path("data/polilabs.kuzu")


def _iter_bill_dirs(base: Path):
    """Yield every bill directory under `base`.

    Mirrors index.build._iter_bill_dirs — auto-detects whether `base`
    is itself a topic directory or the corpus root.
    """
    if not base.is_dir():
        return
    looks_like_topic_dir = any(
        p.is_dir() and (p / "metadata.json").exists()
        for p in base.iterdir()
    )
    if looks_like_topic_dir:
        for bill_dir in sorted(p for p in base.iterdir() if p.is_dir()):
            yield bill_dir
        return
    for topic_dir in sorted(p for p in base.iterdir() if p.is_dir()):
        for bill_dir in sorted(p for p in topic_dir.iterdir() if p.is_dir()):
            yield bill_dir

JURISDICTION_URN = "us"
BIBLIOGRAPHIC_EXTRACTOR_ID = "polilabs/bibliographic_builder@v1"
CITATION_EXTRACTOR_ID = "polilabs/uslm_external_xref_extractor@v1"
DEFINITIONS_EXTRACTOR_ID = "polilabs/definitions_extractor@v1"
AMENDMENTS_EXTRACTOR_ID = "polilabs/amendments_extractor@v1"

# UNWIND chunk size. 2000 keeps peak memory modest while amortizing the
# Cypher round-trip cost over ~2000 rows.
CHUNK = 2000


# -----------------------------------------------------------------------------
# Identifier helpers — URN-style per schema_design.md §1.
# -----------------------------------------------------------------------------

def bill_urn(congress: int, bill_type: str, bill_number: int) -> str:
    return f"bill:{JURISDICTION_URN}/{congress}/{bill_type}/{bill_number}"


def version_urn(bill_id: str, date_iso: str, stage_code: str) -> str:
    return f"{bill_id}@{date_iso}/{stage_code}"


def _slug(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", name.lower()).strip("-")
    return s or "unnamed"


def fallback_sponsor_id(display_name: str, congress: int) -> str:
    h = hashlib.sha1(f"{display_name}|{congress}".encode()).hexdigest()[:10]
    return f"_legacy:{_slug(display_name)[:40]}:{h}"


def bioguide_sponsor_id(bioguide_id: str) -> str:
    return f"person:bioguide/{bioguide_id}"


def _provenance_id_for(label: str) -> str:
    h = hashlib.sha1(label.encode()).hexdigest()[:12]
    return f"prov:{h}"


def _date_or_none(s: str | None) -> date | None:
    """Parse an ISO date prefix into a `datetime.date`.

    Kùzu's Python binding does not implicitly cast STRING → DATE;
    binding a raw ISO string to a DATE column raises BinderException.
    Always pass real `date` objects.
    """
    if not s:
        return None
    try:
        return datetime.fromisoformat(s[:10]).date()
    except ValueError:
        return None


# -----------------------------------------------------------------------------
# Phase-1 accumulators.
# -----------------------------------------------------------------------------

@dataclass
class Accum:
    bills: list[dict[str, Any]] = field(default_factory=list)
    bill_versions: list[dict[str, Any]] = field(default_factory=list)
    sections: list[dict[str, Any]] = field(default_factory=list)
    sponsors: dict[str, dict[str, Any]] = field(default_factory=dict)
    statute_sections: dict[str, dict[str, Any]] = field(default_factory=dict)
    defined_terms: dict[str, dict[str, Any]] = field(default_factory=dict)
    of_jurisdiction: list[dict[str, Any]] = field(default_factory=list)
    has_version: list[dict[str, Any]] = field(default_factory=list)
    has_section: list[dict[str, Any]] = field(default_factory=list)
    parent_of: list[dict[str, Any]] = field(default_factory=list)
    sponsored_by: list[dict[str, Any]] = field(default_factory=list)
    cosponsored_by: list[dict[str, Any]] = field(default_factory=list)
    cites_external: list[dict[str, Any]] = field(default_factory=list)
    defines_edges: list[dict[str, Any]] = field(default_factory=list)
    by_reference_edges: list[dict[str, Any]] = field(default_factory=list)
    amendments: list[dict[str, Any]] = field(default_factory=list)
    amends_edges: list[dict[str, Any]] = field(default_factory=list)
    targets_edges: list[dict[str, Any]] = field(default_factory=list)
    format_counts: dict[str, int] = field(default_factory=dict)
    parse_errors: int = 0
    bills_collected: int = 0
    bills_with_citations: int = 0
    bills_with_definitions: int = 0
    bills_with_amendments: int = 0


_KNOWN_BILL_PREFIXES = (
    "Rep.", "Sen.", "Del.", "Rescom.", "Resident Commissioner",
)


def _accumulate_bill(meta: dict, fmt: str, section_rows: list, acc: Accum) -> None:
    """Phase-1 work for one bill: append rows; no DB I/O."""
    bid = bill_urn(meta["congress"], meta["bill_type"], meta["bill_number"])

    # ----- Bill -----
    latest_action = meta.get("latest_action") or ""
    if ":" in latest_action:
        la_date_str, _, la_text = latest_action.partition(":")
    else:
        la_date_str, la_text = "", latest_action
    primary_sponsor_display = meta.get("sponsor")

    acc.bills.append({
        "bill_id": bid,
        "congress": int(meta["congress"]),
        "bill_type": meta["bill_type"],
        "bill_number": int(meta["bill_number"]),
        "jur": JURISDICTION_URN,
        "title": meta.get("title"),
        "short_title": meta.get("short_title"),
        "primary_subject": meta.get("policy_area"),
        "summary": meta.get("summary_text"),
        "status": (la_text.strip()[:120] or None) if la_text else None,
        "la_date": _date_or_none(la_date_str.strip()),
        "la_text": la_text.strip() or None,
        "tier": meta.get("tier"),
        "stream": meta.get("stream", "legislation"),
        "topic": meta.get("topic", "ai_governance"),
        "cs": float(meta.get("centrality_score") or 0.0),
        "sponsor_name": primary_sponsor_display,
    })
    acc.of_jurisdiction.append({"bid": bid, "urn": JURISDICTION_URN})

    # ----- BillVersion (canonical only) -----
    canonical = meta.get("canonical_version") or {}
    vid: str | None = None
    if canonical.get("date_issued") and canonical.get("version_code"):
        vid = version_urn(bid, canonical["date_issued"], canonical["version_code"])
        acc.bill_versions.append({
            "vid": vid,
            "bid": bid,
            "stage": canonical["version_code"],
            "vd": _date_or_none(canonical["date_issued"]),
            "rec": datetime.now(timezone.utc),
            "fmt": fmt,
            "pkg": canonical.get("package_id"),
        })
        acc.has_version.append({"bid": bid, "vid": vid})

    # ----- Sections -----
    if vid is not None and section_rows:
        # The parser keys section_id by the input bill_id prefix; re-key
        # all section_ids to the URN-style bill_id for graph consistency.
        old_prefix = section_rows[0].bill_id

        def rekey(s: str | None) -> str | None:
            if s is None:
                return None
            return s.replace(old_prefix, bid, 1)

        for r in section_rows:
            new_sid = rekey(r.section_id)
            acc.sections.append({
                "sid": new_sid,
                "vid": vid,
                "level": r.level,
                "enum": r.enum,
                "heading": r.heading,
                "text_self": r.text_self,
                "text_full": r.text_full,
                "citation": r.canonical_citation,
                "ordinal": int(r.ordinal),
                "xml_id": r.xml_id,
            })
            if r.parent_section_id is None:
                acc.has_section.append({
                    "vid": vid, "sid": new_sid, "ord": int(r.ordinal),
                })
            else:
                acc.parent_of.append({
                    "pid": rekey(r.parent_section_id),
                    "cid": new_sid,
                    "ord": int(r.ordinal),
                })

    # ----- Primary sponsor -----
    if primary_sponsor_display:
        sid = fallback_sponsor_id(primary_sponsor_display, meta["congress"])
        if sid not in acc.sponsors:
            acc.sponsors[sid] = {
                "sid": sid, "bioguide": None, "display": primary_sponsor_display,
                "first": None, "last": None, "party": None, "state": None,
                "district": None, "id_source": "fallback",
            }
        acc.sponsored_by.append({
            "bid": bid, "sid": sid,
            "d": _date_or_none(meta.get("introduced_date")),
        })

    # ----- Cosponsors -----
    seen_in_bill: set[str] = set()
    for cs in meta.get("cosponsors", []) or []:
        bioguide = cs.get("bioguideId")
        if not bioguide:
            continue
        sid = bioguide_sponsor_id(bioguide)
        if sid in seen_in_bill:
            continue
        seen_in_bill.add(sid)
        if sid not in acc.sponsors:
            acc.sponsors[sid] = {
                "sid": sid,
                "bioguide": bioguide,
                "display": cs.get("fullName") or cs.get("lastName") or bioguide,
                "first": cs.get("firstName"),
                "last": cs.get("lastName"),
                "party": cs.get("party"),
                "state": cs.get("state"),
                "district": str(cs.get("district")) if cs.get("district") is not None else None,
                "id_source": "bioguide",
            }
        acc.cosponsored_by.append({
            "bid": bid, "sid": sid,
            "d": _date_or_none(cs.get("sponsorshipDate")),
            "orig": bool(cs.get("isOriginalCosponsor")),
        })

    acc.bills_collected += 1
    acc.format_counts[fmt] = acc.format_counts.get(fmt, 0) + 1


def _accumulate_definitions(
    meta: dict,
    xml_path: Path,
    valid_section_ids: set[str],
    acc: Accum,
) -> None:
    """Phase-1 definition extraction.

    Appends DefinedTerm rows + DEFINES edges + BY_REFERENCE edges
    (when the definition references a USC section). Also lazily MERGEs
    the BY_REFERENCE target into statute_sections in case PR2's citation
    pass didn't already capture it (some bills define-by-reference to a
    USC section they don't otherwise cite in body text).

    `valid_section_ids` is the set of section IDs that parse_uslm
    produced for this bill. DefinedTerms whose defining_section_id isn't
    in that set are silently dropped — mostly an artifact of USLM-format
    coverage gaps in parse_uslm (118-hr-5009 in particular). They'll
    return when parse_uslm gets a USLM-coverage fix.
    """
    bid = bill_urn(meta["congress"], meta["bill_type"], meta["bill_number"])
    terms = extract_defined_terms(xml_path, bill_id=bid)
    if not terms:
        return
    bill_had_any = False
    for t in terms:
        if t.defining_section_id not in valid_section_ids:
            continue
        bill_had_any = True
        # Dedupe DefinedTerm by ID (cross-bill collisions are not
        # expected because the ID embeds the container_section_id which
        # embeds the bill URN).
        if t.defined_term_id not in acc.defined_terms:
            acc.defined_terms[t.defined_term_id] = {
                "dtid": t.defined_term_id,
                "surface": t.surface_form,
                "defining_section_id": t.defining_section_id,
                "scope": t.scope,
                "def_text": t.definition_text,
                "def_type": t.definition_type,
                "br_target": t.by_reference_statute_section_id,
            }
        # DEFINES edge: Section (defining_section_id) -> DefinedTerm
        acc.defines_edges.append({
            "sid": t.defining_section_id,
            "dtid": t.defined_term_id,
            "def_type": t.definition_type,
        })
        # BY_REFERENCE edge: DefinedTerm -> StatuteSection (USC target)
        if t.by_reference_statute_section_id:
            # Make sure the target StatuteSection exists in the accumulator.
            tgt = t.by_reference_statute_section_id
            if tgt not in acc.statute_sections:
                acc.statute_sections[tgt] = {
                    "ssid": tgt,
                    "sid": "/".join(tgt.split("/")[:-1]),  # statute:us/usc/{title}
                    "enum_path": "",
                    "citation": t.by_reference_canonical or tgt,
                }
            acc.by_reference_edges.append({
                "dtid": t.defined_term_id,
                "ssid": tgt,
                "confidence": 1.0,
            })
    if bill_had_any:
        acc.bills_with_definitions += 1


def _accumulate_amendments(
    meta: dict,
    xml_path: Path,
    valid_section_ids: set[str],
    acc: Accum,
) -> None:
    """Phase-1 amendment extraction.

    Appends AmendmentOperation rows + AMENDS edges + TARGETS edges (to
    StatuteSection). Also lazily MERGEs the target StatuteSection if
    it wasn't already captured by PR2's citation pass — some amendments
    target statutes that the bill doesn't otherwise cite in body text.
    """
    bid = bill_urn(meta["congress"], meta["bill_type"], meta["bill_number"])
    amends = extract_amendments(xml_path, bill_id=bid)
    if not amends:
        return
    bill_had_any = False
    for a in amends:
        if a.source_section_id not in valid_section_ids:
            # Source section wasn't emitted by parse_uslm (USLM coverage
            # gaps — same class of bug noted in PR3). Silently drop.
            continue
        bill_had_any = True

        acc.amendments.append({
            "amend_id": a.amendment_id,
            "src_sid": a.source_section_id,
            "op": a.operation_type,
            "op_text": a.operation_text,
            "locator": a.target_locator_json,
            "before": a.before_text,
            "after": a.after_text,
            "xml_ref_id": a.xml_ref_id,
            "unverified": True,
        })
        acc.amends_edges.append({
            "src_sid": a.source_section_id,
            "amend_id": a.amendment_id,
            "xml_ref_id": a.xml_ref_id,
        })
        if a.target_statute_section_id is not None:
            # Lazily ensure the StatuteSection target exists.
            if a.target_statute_section_id not in acc.statute_sections:
                acc.statute_sections[a.target_statute_section_id] = {
                    "ssid": a.target_statute_section_id,
                    "sid": "/".join(a.target_statute_section_id.split("/")[:-1]),
                    "enum_path": "",
                    "citation": a.target_canonical_citation or a.target_statute_section_id,
                }
            acc.targets_edges.append({
                "amend_id": a.amendment_id,
                "ssid": a.target_statute_section_id,
                "enum_path": "",  # PR4 doesn't parse (b)(2) into enum_path yet
            })
        # If target_statute_section_id is None, the AmendmentOperation
        # exists but with no TARGETS edge — the locator JSON records what
        # we know. PR4.1 / Public-Law support fills this in later.
    if bill_had_any:
        acc.bills_with_amendments += 1


def _accumulate_citations(
    meta: dict,
    xml_path: Path,
    citation_provenance_id: str,
    acc: Accum,
) -> None:
    """Phase-1 citation extraction. Appends StatuteSection rows and
    CITES_EXTERNAL edge rows to the accumulator.
    """
    bid = bill_urn(meta["congress"], meta["bill_type"], meta["bill_number"])
    edges = extract_external_citations(xml_path, bill_id=bid)
    if not edges:
        return
    acc.bills_with_citations += 1
    for e in edges:
        # Lazily dedupe StatuteSection nodes — many bills cite the same
        # USC section.
        if e.target_statute_section_id not in acc.statute_sections:
            acc.statute_sections[e.target_statute_section_id] = {
                "ssid": e.target_statute_section_id,
                "sid": e.target_statute_id,
                "enum_path": "",  # parsable-cite is section-level only
                "citation": e.target_canonical_citation,
            }
        acc.cites_external.append({
            "src": e.source_section_id,
            "tgt": e.target_statute_section_id,
            "raw": e.raw_text,
            "xml_ref_id": e.xml_ref_id,
            "derivation": "mechanical",
            "confidence": 1.0,
            "pid": citation_provenance_id,
        })


# -----------------------------------------------------------------------------
# Phase-2 bulk inserts: one UNWIND per table, chunked.
# -----------------------------------------------------------------------------

def _chunked(rows: list[dict[str, Any]], size: int = CHUNK):
    for i in range(0, len(rows), size):
        yield rows[i:i + size]


def _bulk(conn: kuzu.Connection, label: str, rows: list[dict[str, Any]], query: str) -> None:
    """Run an UNWIND query in chunks over rows. Skips silently if rows is empty."""
    if not rows:
        return
    total = len(rows)
    done = 0
    for chunk in _chunked(rows):
        conn.execute(query, {"rows": chunk})
        done += len(chunk)


def _bulk_create_bills(conn: kuzu.Connection, rows: list) -> None:
    _bulk(conn, "Bill", rows, """
        UNWIND $rows AS r
        CREATE (:Bill {
            bill_id: r.bill_id, congress: r.congress, bill_type: r.bill_type,
            bill_number: r.bill_number, jurisdiction_urn: r.jur,
            official_title: r.title, short_title: r.short_title,
            primary_subject: r.primary_subject, summary_text: r.summary,
            current_status: r.status, latest_action_date: r.la_date,
            latest_action_text: r.la_text, tier: r.tier, stream: r.stream,
            topic: r.topic,
            centrality_score: r.cs, sponsor_display_name: r.sponsor_name
        })""")


def _bulk_create_bill_versions(conn: kuzu.Connection, rows: list) -> None:
    _bulk(conn, "BillVersion", rows, """
        UNWIND $rows AS r
        CREATE (:BillVersion {
            version_id: r.vid, bill_id: r.bid, stage: r.stage,
            version_observed_at: r.vd, knowledge_recorded_at: r.rec,
            xml_format: r.fmt, source_package_id: r.pkg, is_current: true
        })""")


def _bulk_create_sections(conn: kuzu.Connection, rows: list) -> None:
    _bulk(conn, "Section", rows, """
        UNWIND $rows AS r
        CREATE (:Section {
            section_id: r.sid, version_id: r.vid, level: r.level,
            enum: r.enum, heading: r.heading, text_self: r.text_self,
            text_full: r.text_full, canonical_citation: r.citation,
            ordinal: r.ordinal, xml_id: r.xml_id
        })""")


def _bulk_merge_sponsors(conn: kuzu.Connection, rows: list) -> None:
    # All sponsors are deduplicated in the accumulator already, so CREATE
    # is safe and faster than MERGE.
    _bulk(conn, "Sponsor", rows, """
        UNWIND $rows AS r
        CREATE (:Sponsor {
            sponsor_id: r.sid, bioguide_id: r.bioguide, display_name: r.display,
            first_name: r.first, last_name: r.last, party: r.party,
            state: r.state, district: r.district, id_source: r.id_source
        })""")


def _bulk_create_of_jurisdiction(conn: kuzu.Connection, rows: list) -> None:
    _bulk(conn, "OF_JURISDICTION", rows, """
        UNWIND $rows AS r
        MATCH (b:Bill {bill_id: r.bid}), (j:Jurisdiction {urn: r.urn})
        CREATE (b)-[:OF_JURISDICTION]->(j)""")


def _bulk_create_has_version(conn: kuzu.Connection, rows: list) -> None:
    _bulk(conn, "HAS_VERSION", rows, """
        UNWIND $rows AS r
        MATCH (b:Bill {bill_id: r.bid}), (v:BillVersion {version_id: r.vid})
        CREATE (b)-[:HAS_VERSION {is_current: true}]->(v)""")


def _bulk_create_has_section(conn: kuzu.Connection, rows: list) -> None:
    _bulk(conn, "HAS_SECTION", rows, """
        UNWIND $rows AS r
        MATCH (v:BillVersion {version_id: r.vid}), (s:Section {section_id: r.sid})
        CREATE (v)-[:HAS_SECTION {ordinal: r.ord}]->(s)""")


def _bulk_create_parent_of(conn: kuzu.Connection, rows: list) -> None:
    _bulk(conn, "PARENT_OF", rows, """
        UNWIND $rows AS r
        MATCH (p:Section {section_id: r.pid}), (c:Section {section_id: r.cid})
        CREATE (p)-[:PARENT_OF {ordinal: r.ord}]->(c)""")


def _bulk_create_sponsored_by(conn: kuzu.Connection, rows: list) -> None:
    _bulk(conn, "SPONSORED_BY", rows, """
        UNWIND $rows AS r
        MATCH (b:Bill {bill_id: r.bid}), (s:Sponsor {sponsor_id: r.sid})
        CREATE (b)-[:SPONSORED_BY {sponsorship_date: r.d}]->(s)""")


def _bulk_create_cosponsored_by(conn: kuzu.Connection, rows: list) -> None:
    _bulk(conn, "COSPONSORED_BY", rows, """
        UNWIND $rows AS r
        MATCH (b:Bill {bill_id: r.bid}), (s:Sponsor {sponsor_id: r.sid})
        CREATE (b)-[:COSPONSORED_BY {sponsorship_date: r.d, is_original: r.orig}]->(s)""")


def _bulk_create_statute_sections(conn: kuzu.Connection, rows: list) -> None:
    _bulk(conn, "StatuteSection", rows, """
        UNWIND $rows AS r
        CREATE (:StatuteSection {
            statute_section_id: r.ssid, statute_id: r.sid,
            enum_path: r.enum_path, canonical_citation: r.citation
        })""")


def _bulk_create_cites_external(conn: kuzu.Connection, rows: list) -> None:
    _bulk(conn, "CITES_EXTERNAL", rows, """
        UNWIND $rows AS r
        MATCH (src:Section {section_id: r.src}),
              (tgt:StatuteSection {statute_section_id: r.tgt})
        CREATE (src)-[:CITES_EXTERNAL {
            raw_text: r.raw, xml_ref_id: r.xml_ref_id,
            derivation: r.derivation, confidence: r.confidence,
            provenance_id: r.pid
        }]->(tgt)""")


def _bulk_create_defined_terms(conn: kuzu.Connection, rows: list) -> None:
    _bulk(conn, "DefinedTerm", rows, """
        UNWIND $rows AS r
        CREATE (:DefinedTerm {
            defined_term_id: r.dtid, surface_form: r.surface,
            defining_section_id: r.defining_section_id,
            scope: r.scope, definition_text: r.def_text,
            definition_type: r.def_type,
            by_reference_target_id: r.br_target
        })""")


def _bulk_create_defines(conn: kuzu.Connection, rows: list) -> None:
    _bulk(conn, "DEFINES", rows, """
        UNWIND $rows AS r
        MATCH (s:Section {section_id: r.sid}),
              (d:DefinedTerm {defined_term_id: r.dtid})
        CREATE (s)-[:DEFINES {definition_type: r.def_type}]->(d)""")


def _bulk_create_by_reference(conn: kuzu.Connection, rows: list) -> None:
    _bulk(conn, "BY_REFERENCE", rows, """
        UNWIND $rows AS r
        MATCH (d:DefinedTerm {defined_term_id: r.dtid}),
              (s:StatuteSection {statute_section_id: r.ssid})
        CREATE (d)-[:BY_REFERENCE {confidence: r.confidence}]->(s)""")


def _bulk_create_amendments(conn: kuzu.Connection, rows: list) -> None:
    _bulk(conn, "AmendmentOperation", rows, """
        UNWIND $rows AS r
        CREATE (:AmendmentOperation {
            amendment_id: r.amend_id, source_section_id: r.src_sid,
            operation_type: r.op,
            target_locator_json: r.locator,
            before_text: r.before, after_text: r.after,
            target_text_unverified: r.unverified
        })""")


def _bulk_create_amends(conn: kuzu.Connection, rows: list) -> None:
    _bulk(conn, "AMENDS", rows, """
        UNWIND $rows AS r
        MATCH (s:Section {section_id: r.src_sid}),
              (a:AmendmentOperation {amendment_id: r.amend_id})
        CREATE (s)-[:AMENDS {xml_ref_id: r.xml_ref_id}]->(a)""")


def _bulk_create_targets(conn: kuzu.Connection, rows: list) -> None:
    _bulk(conn, "TARGETS", rows, """
        UNWIND $rows AS r
        MATCH (a:AmendmentOperation {amendment_id: r.amend_id}),
              (t:StatuteSection {statute_section_id: r.ssid})
        CREATE (a)-[:TARGETS {enum_path_in_target: r.enum_path}]->(t)""")


# -----------------------------------------------------------------------------
# DB lifecycle.
# -----------------------------------------------------------------------------

def _open_fresh_db(db_path: Path) -> tuple[kuzu.Database, kuzu.Connection]:
    """Delete and recreate the Kùzu DB at db_path. Returns (db, conn)."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        if db_path.is_dir():
            shutil.rmtree(db_path)
        else:
            db_path.unlink()
    wal = db_path.with_suffix(db_path.suffix + ".wal")
    if wal.exists():
        wal.unlink()
    db = kuzu.Database(str(db_path))
    conn = kuzu.Connection(db)
    apply_schema(conn)
    return db, conn


def _seed_static_nodes(conn: kuzu.Connection) -> dict[str, str]:
    """Insert per-build seed nodes: Jurisdiction, Extractors, ProvenanceRecords.

    Returns a dict mapping extractor_id → its run-specific provenance_id,
    so per-edge inserts can attach the right ProvenanceRecord.
    """
    conn.execute(
        "CREATE (:Jurisdiction {urn: $urn, name: $name, legal_system: $ls})",
        {"urn": JURISDICTION_URN, "name": "United States (federal)", "ls": "common_law"},
    )
    now = datetime.now(timezone.utc)
    pids: dict[str, str] = {}

    for eid, kind in (
        (BIBLIOGRAPHIC_EXTRACTOR_ID, "parser"),
        (CITATION_EXTRACTOR_ID, "parser"),
        (DEFINITIONS_EXTRACTOR_ID, "parser"),
        (AMENDMENTS_EXTRACTOR_ID, "parser"),
    ):
        conn.execute(
            "CREATE (:Extractor {extractor_id: $eid, version: $v, kind: $k})",
            {"eid": eid, "v": "1.0", "k": kind},
        )
        pid = _provenance_id_for(f"{eid}:{now.isoformat()}")
        conn.execute(
            """CREATE (:ProvenanceRecord {
                 provenance_id: $pid, extractor_id: $eid,
                 derived_at: $derived_at, confidence: 1.0
               })""",
            {"pid": pid, "eid": eid, "derived_at": now},
        )
        conn.execute(
            """MATCH (e:Extractor {extractor_id: $eid}),
                     (p:ProvenanceRecord {provenance_id: $pid})
               CREATE (e)-[:PRODUCED]->(p)""",
            {"eid": eid, "pid": pid},
        )
        pids[eid] = pid
    return pids


def build_graph(
    *,
    corpus_dir: Path = CORPUS_BASE,
    db_path: Path = GRAPH_PATH,
    verbose: bool = True,
) -> dict:
    db, conn = _open_fresh_db(db_path)
    extractor_pids = _seed_static_nodes(conn)
    citation_pid = extractor_pids[CITATION_EXTRACTOR_ID]

    # ----- Phase 1: collect -----
    acc = Accum()
    bill_dirs = list(_iter_bill_dirs(corpus_dir))
    for i, d in enumerate(bill_dirs):
        meta_path = d / "metadata.json"
        xml_path = d / "bill.xml"
        if not meta_path.exists() or not xml_path.exists():
            continue
        meta = json.loads(meta_path.read_text())
        try:
            section_rows, fmt = parse_bill_xml(
                xml_path,
                bill_id=meta["bill_id"],
                congress=meta["congress"],
                bill_type=meta["bill_type"],
                bill_number=meta["bill_number"],
            )
        except Exception as e:
            acc.parse_errors += 1
            if verbose:
                print(f"[parse-error] {meta['bill_id']}: {type(e).__name__}: {e}")
            continue
        try:
            _accumulate_bill(meta, fmt, section_rows, acc)
        except Exception as e:
            acc.parse_errors += 1
            if verbose:
                print(f"[collect-error] {meta['bill_id']}: {type(e).__name__}: {e}")
            continue
        try:
            _accumulate_citations(meta, xml_path, citation_pid, acc)
        except Exception as e:
            # Citation-extraction failures don't abort the bibliographic
            # ingest — just log and continue with empty citations.
            if verbose:
                print(f"[citation-error] {meta['bill_id']}: {type(e).__name__}: {e}")
        # parse_uslm produces section_ids prefixed with the LEGACY
        # bill_id; the accumulator stores them with the URN prefix.
        # Build the valid-set in URN form so it matches what the
        # downstream extractors will produce.
        urn_bid = bill_urn(meta["congress"], meta["bill_type"], meta["bill_number"])
        old_prefix = meta["bill_id"]
        valid_sids = {
            r.section_id.replace(old_prefix, urn_bid, 1) for r in section_rows
        }
        try:
            _accumulate_definitions(meta, xml_path, valid_sids, acc)
        except Exception as e:
            if verbose:
                print(f"[definition-error] {meta['bill_id']}: {type(e).__name__}: {e}")
        try:
            _accumulate_amendments(meta, xml_path, valid_sids, acc)
        except Exception as e:
            if verbose:
                print(f"[amendment-error] {meta['bill_id']}: {type(e).__name__}: {e}")
        if verbose and (i + 1) % 50 == 0:
            print(f"  collected {i + 1}/{len(bill_dirs)} bills; sections so far: {len(acc.sections)}")

    if verbose:
        print(f"  phase 1 done: {acc.bills_collected} bills, {len(acc.sections)} sections, "
              f"{len(acc.sponsors)} unique sponsors, "
              f"{len(acc.cites_external)} citations across {acc.bills_with_citations} bills, "
              f"{len(acc.defined_terms)} defined terms across {acc.bills_with_definitions} bills, "
              f"{len(acc.amendments)} amendments across {acc.bills_with_amendments} bills")
        print(f"  phase 2 starting: bulk insert via UNWIND (chunk={CHUNK})")

    # ----- Phase 2: bulk insert (order matters — nodes before their edges) -----
    _bulk_create_bills(conn, acc.bills)
    _bulk_create_bill_versions(conn, acc.bill_versions)
    _bulk_create_sections(conn, acc.sections)
    _bulk_merge_sponsors(conn, list(acc.sponsors.values()))
    _bulk_create_statute_sections(conn, list(acc.statute_sections.values()))
    _bulk_create_defined_terms(conn, list(acc.defined_terms.values()))
    _bulk_create_amendments(conn, acc.amendments)
    _bulk_create_of_jurisdiction(conn, acc.of_jurisdiction)
    _bulk_create_has_version(conn, acc.has_version)
    _bulk_create_has_section(conn, acc.has_section)
    _bulk_create_parent_of(conn, acc.parent_of)
    _bulk_create_sponsored_by(conn, acc.sponsored_by)
    _bulk_create_cosponsored_by(conn, acc.cosponsored_by)
    _bulk_create_cites_external(conn, acc.cites_external)
    _bulk_create_defines(conn, acc.defines_edges)
    _bulk_create_by_reference(conn, acc.by_reference_edges)
    _bulk_create_amends(conn, acc.amends_edges)
    _bulk_create_targets(conn, acc.targets_edges)

    # ----- Final-state counts via Cypher -----
    def _scalar(query: str) -> int:
        r = conn.execute(query)
        return int(r.get_next()[0]) if r.has_next() else 0

    stats = {
        "bills_collected": acc.bills_collected,
        "parse_errors": acc.parse_errors,
        "format": acc.format_counts,
        "bills_in_db": _scalar("MATCH (b:Bill) RETURN COUNT(b)"),
        "bill_versions_in_db": _scalar("MATCH (v:BillVersion) RETURN COUNT(v)"),
        "sections_in_db": _scalar("MATCH (s:Section) RETURN COUNT(s)"),
        "sponsors_in_db": _scalar("MATCH (s:Sponsor) RETURN COUNT(s)"),
        "statute_sections_in_db": _scalar("MATCH (s:StatuteSection) RETURN COUNT(s)"),
        "has_section_edges": _scalar("MATCH ()-[r:HAS_SECTION]->() RETURN COUNT(r)"),
        "parent_of_edges": _scalar("MATCH ()-[r:PARENT_OF]->() RETURN COUNT(r)"),
        "sponsored_by_edges": _scalar("MATCH ()-[r:SPONSORED_BY]->() RETURN COUNT(r)"),
        "cosponsored_by_edges": _scalar("MATCH ()-[r:COSPONSORED_BY]->() RETURN COUNT(r)"),
        "cites_external_edges": _scalar("MATCH ()-[r:CITES_EXTERNAL]->() RETURN COUNT(r)"),
        "defined_terms_in_db": _scalar("MATCH (d:DefinedTerm) RETURN COUNT(d)"),
        "defines_edges": _scalar("MATCH ()-[r:DEFINES]->() RETURN COUNT(r)"),
        "by_reference_edges": _scalar("MATCH ()-[r:BY_REFERENCE]->() RETURN COUNT(r)"),
        "amendments_in_db": _scalar("MATCH (a:AmendmentOperation) RETURN COUNT(a)"),
        "amends_edges": _scalar("MATCH ()-[r:AMENDS]->() RETURN COUNT(r)"),
        "targets_edges": _scalar("MATCH ()-[r:TARGETS]->() RETURN COUNT(r)"),
        "bills_with_citations": acc.bills_with_citations,
        "bills_with_definitions": acc.bills_with_definitions,
        "bills_with_amendments": acc.bills_with_amendments,
    }
    return stats
