"""Implementations of the six api/SPEC.md primitives against polilabs.db.

The DB is a derived index of data/corpus/legislation/. It can be rebuilt at
any time via scripts/build_index.py — corpus files are the source of truth.

Design contracts (from api/SPEC.md) honoured here:
- Hierarchical retrieval: get_bill returns a section ToC, not bodies.
- Verbatim text + canonical citation always travel together (Section).
- Stable opaque IDs: section_id = '{bill_id}::{xml_id}' from the indexer.
- Typed edges only: citations.type CHECK constraint enforces this.
- Point-in-time: v1 has one canonical version per bill, so as_of is honoured
  by parameter but returns the current version with a provenance note.
- Provenance on every response.
- in_scope distinguishes empty-in-scope from out-of-scope queries.
- Honest unknowns: get_section returns not_found=True rather than raising.
"""
from __future__ import annotations

import os
import re
import sqlite3
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal

from .types import (
    AdjacencySummary,
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

DB_PATH = Path(os.environ.get("POLILABS_DB", "data/polilabs.db"))

_CONN: sqlite3.Connection | None = None


def _db() -> sqlite3.Connection:
    """Lazy-open the index DB; one connection per process."""
    global _CONN
    if _CONN is None:
        if not DB_PATH.exists():
            raise FileNotFoundError(
                f"polilabs.db not found at {DB_PATH}. "
                "Run `python scripts/build_index.py` to build the index from data/corpus/."
            )
        _CONN = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _CONN.row_factory = sqlite3.Row
    return _CONN


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def _make_provenance(
    sources: list[str],
    *,
    notes: str | None = None,
) -> Provenance:
    return Provenance(
        sources=sources,
        last_verified=_now_utc(),
        agreement=None,  # Phase 4
        notes=notes,
    )


def _bill_sources(row: sqlite3.Row) -> list[str]:
    pkg = row["canonical_package_id"]
    return [
        f"govinfo:{pkg}" if pkg else "govinfo:unknown",
        f"congress.gov:{row['congress']}/{row['bill_type']}/{row['bill_number']}",
    ]


# ----- search_corpus -----

_FTS_SYNTAX_CHARS = re.compile(r'[\"\*]|\b(AND|OR|NOT|NEAR)\b')


def _normalize_fts_query(q: str) -> str:
    """Pass FTS-style queries through; wrap bare-token queries to require all terms.

    Examples:
      'frontier model'      -> '"frontier" "model"'      (both must appear)
      '"frontier model"'    -> '"frontier model"'        (phrase, untouched)
      'AI OR ML'            -> 'AI OR ML'                (untouched)
    """
    if _FTS_SYNTAX_CHARS.search(q):
        return q
    tokens = [t for t in re.split(r"\s+", q.strip()) if t]
    if not tokens:
        return q
    return " ".join(f'"{t}"' for t in tokens)


def _matched_keywords(query: str, hit_row: sqlite3.Row) -> list[str]:
    """Best-effort: which query tokens appear in the bill's metadata."""
    tokens = [t.strip('"') for t in re.findall(r'"[^"]+"|\S+', query) if t.strip('"').isalnum() or " " in t]
    if not tokens:
        tokens = [t for t in re.split(r"\s+", query) if t and t.upper() not in {"AND", "OR", "NOT", "NEAR"}]
    hay_parts = [hit_row[c] or "" for c in ("title", "short_title", "summary_text", "policy_area")]
    hay = " ".join(hay_parts).lower()
    found = [t for t in tokens if t.lower() in hay]
    return found


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
    conn = _db()
    streams = streams or ["legislation"]

    # Out-of-scope: any requested stream that isn't 'legislation' (v1)
    requested_oos = [s for s in streams if s != "legislation"]
    if requested_oos:
        coverage = _coverage_note_static(conn)
        return SearchResults(
            hits=[],
            total=0,
            query=query,
            coverage_note=f"Requested streams {requested_oos} are out of v1 scope. {coverage}",
            in_scope=False,
        )

    # Out-of-scope: requested congresses outside our range
    in_corpus_congresses = {r[0] for r in conn.execute("SELECT DISTINCT congress FROM bills")}
    if congresses and not any(c in in_corpus_congresses for c in congresses):
        return SearchResults(
            hits=[],
            total=0,
            query=query,
            coverage_note=f"Requested congresses {congresses} are outside v1 corpus (have {sorted(in_corpus_congresses)}).",
            in_scope=False,
        )

    fts_q = _normalize_fts_query(query)
    matched: dict[str, float] = {}

    try:
        for r in conn.execute(
            "SELECT bill_id, bm25(bills_fts) AS rank FROM bills_fts WHERE bills_fts MATCH ?",
            (fts_q,),
        ):
            matched[r["bill_id"]] = r["rank"]
        # FTS5 disallows bm25() inside aggregations — pull raw rows and reduce in Python.
        section_ranks: dict[str, float] = {}
        for r in conn.execute(
            "SELECT bill_id, bm25(sections_fts) AS rank FROM sections_fts WHERE sections_fts MATCH ?",
            (fts_q,),
        ):
            bid = r["bill_id"]
            cur = section_ranks.get(bid)
            if cur is None or r["rank"] < cur:
                section_ranks[bid] = r["rank"]
        for bid, srank in section_ranks.items():
            if bid not in matched or srank < matched[bid]:
                matched[bid] = srank
    except sqlite3.OperationalError as e:
        return SearchResults(
            hits=[], total=0, query=query,
            coverage_note=f"FTS5 syntax error on query {query!r}: {e}. "
                          "Use phrase-quotes for multi-word terms (e.g. \"frontier model\").",
            in_scope=True,
        )

    if not matched:
        return SearchResults(
            hits=[], total=0, query=query,
            coverage_note=_coverage_note_static(conn),
            in_scope=True,
        )

    placeholders = ",".join("?" * len(matched))
    sql = f"SELECT * FROM bills WHERE bill_id IN ({placeholders})"
    params: list = list(matched.keys())
    if date_range:
        sql += " AND introduced_date BETWEEN ? AND ?"
        params += [date_range[0].isoformat(), date_range[1].isoformat()]
    if congresses:
        cs = ",".join("?" * len(congresses))
        sql += f" AND congress IN ({cs})"
        params += list(congresses)
    if tier:
        sql += " AND tier = ?"
        params.append(tier)

    rows = conn.execute(sql, params).fetchall()

    hits: list[SearchHit] = []
    for r in rows:
        bid = r["bill_id"]
        intro = _date(r["introduced_date"]) or date.min
        hits.append(SearchHit(
            bill_id=bid,
            title=r["title"] or "",
            short_title=r["short_title"],
            summary=(r["summary_text"] or "")[:500] if r["summary_text"] else None,
            sponsor=r["sponsor"] or "",
            congress=r["congress"],
            introduced_date=intro,
            tier=r["tier"] or "B",
            stream=r["stream"] or "legislation",
            matched_keywords=_matched_keywords(query, r),
            relevance_score=-matched[bid],  # bm25 is negative-better; flip
            provenance=_make_provenance(_bill_sources(r)),
        ))
    hits.sort(key=lambda h: h.relevance_score, reverse=True)
    total = len(hits)
    hits = hits[offset:offset + limit]

    return SearchResults(
        hits=hits,
        total=total,
        query=query,
        coverage_note=_coverage_note_static(conn),
        in_scope=True,
    )


def _coverage_note_static(conn: sqlite3.Connection) -> str:
    n_bills = conn.execute("SELECT COUNT(*) FROM bills").fetchone()[0]
    congresses = sorted({r[0] for r in conn.execute("SELECT DISTINCT congress FROM bills")})
    return (
        f"{n_bills} bills, "
        f"Congress {min(congresses)}-{max(congresses)}, "
        f"AI-governance corpus v1.0 (legislation stream only)"
    )


# ----- get_bill -----

def get_bill(bill_id: str) -> Bill:
    conn = _db()
    bill = conn.execute("SELECT * FROM bills WHERE bill_id = ?", (bill_id,)).fetchone()
    if bill is None:
        raise KeyError(f"bill_id {bill_id!r} not in corpus")

    cosponsors = [
        f"{r['name']} ({r['party']}-{r['state']})" if r["party"] and r["state"] else r["name"]
        for r in conn.execute(
            "SELECT name, party, state FROM cosponsors WHERE bill_id = ? ORDER BY sponsorship_date",
            (bill_id,),
        )
    ]

    # Section ToC: just top-level sections (parent IS NULL), ordered
    section_refs = [
        SectionRef(
            section_id=r["section_id"],
            bill_id=bill_id,
            heading=r["heading"] or (f"Section {r['enum']}" if r["enum"] else "(unnamed)"),
            parent_section_id=None,
            version_count=1,  # v1: one canonical version per bill
        )
        for r in conn.execute(
            "SELECT section_id, heading, enum FROM sections "
            "WHERE bill_id = ? AND parent_section_id IS NULL ORDER BY ordinal",
            (bill_id,),
        )
    ]

    versions = [
        BillVersion(
            label=r["version_code"],
            version_date=_date(r["date_issued"]) or date.min,
            package_id=r["package_id"],
        )
        for r in conn.execute(
            "SELECT package_id, version_code, date_issued FROM bill_versions "
            "WHERE bill_id = ? ORDER BY date_issued",
            (bill_id,),
        )
    ]

    return Bill(
        bill_id=bill_id,
        congress=bill["congress"],
        bill_type=bill["bill_type"],
        bill_number=bill["bill_number"],
        title=bill["title"] or "",
        short_title=bill["short_title"],
        sponsor=bill["sponsor"] or "",
        cosponsors=cosponsors,
        introduced_date=_date(bill["introduced_date"]) or date.min,
        latest_action=f"{bill['latest_action_date'] or ''}: {bill['latest_action_text'] or ''}".strip(": "),
        status=bill["latest_action_text"] or "",
        tier=bill["tier"] or "B",
        stream=bill["stream"] or "legislation",
        sections=section_refs,
        versions=versions,
        provenance=_make_provenance(_bill_sources(bill)),
    )


# ----- get_section -----

def _adjacency(conn: sqlite3.Connection, section_id: str) -> AdjacencySummary:
    out_rows = conn.execute(
        "SELECT type, COUNT(*) c FROM citations WHERE source_section_id = ? GROUP BY type",
        (section_id,),
    ).fetchall()
    in_rows = conn.execute(
        "SELECT type, COUNT(*) c FROM citations WHERE target_section_id = ? GROUP BY type",
        (section_id,),
    ).fetchall()
    by_out: dict[CitationType, int] = {r["type"]: r["c"] for r in out_rows}
    by_in: dict[CitationType, int] = {r["type"]: r["c"] for r in in_rows}
    return AdjacencySummary(
        citations_out_count=sum(by_out.values()),
        citations_in_count=sum(by_in.values()),
        by_type_out=by_out,
        by_type_in=by_in,
    )


def get_section(section_id: str, *, as_of: date | None = None) -> Section:
    conn = _db()
    row = conn.execute(
        "SELECT s.*, b.canonical_version_date FROM sections s "
        "JOIN bills b USING (bill_id) WHERE section_id = ?",
        (section_id,),
    ).fetchone()
    if row is None:
        bill_id = section_id.split("::", 1)[0] if "::" in section_id else ""
        sources = [f"polilabs:db@{DB_PATH}"]
        return Section(
            section_id=section_id, bill_id=bill_id, heading="", text=None,
            canonical_citation="", parent_section_id=None, child_section_ids=[],
            version_date=None, version_label=None, is_current=False,
            adjacency_summary=AdjacencySummary(0, 0, {}, {}),
            provenance=_make_provenance(sources, notes="section_id not found in corpus"),
            not_found=True,
        )

    children = [
        r["section_id"]
        for r in conn.execute(
            "SELECT section_id FROM sections WHERE parent_section_id = ? ORDER BY ordinal",
            (section_id,),
        )
    ]

    bill_meta = conn.execute(
        "SELECT canonical_package_id, congress, bill_type, bill_number, canonical_version_code "
        "FROM bills WHERE bill_id = ?",
        (row["bill_id"],),
    ).fetchone()

    sources = [
        f"govinfo:{bill_meta['canonical_package_id']}" if bill_meta else "govinfo:unknown",
    ]
    notes = None
    if as_of is not None:
        notes = (
            f"as_of={as_of.isoformat()} requested, but v1 corpus stores one canonical version per bill. "
            f"Returned version is {bill_meta['canonical_version_code']} dated {row['canonical_version_date']}."
        )

    return Section(
        section_id=section_id,
        bill_id=row["bill_id"],
        heading=row["heading"] or "",
        text=row["text_full"] or row["text_self"] or "",
        canonical_citation=row["canonical_citation"],
        parent_section_id=row["parent_section_id"],
        child_section_ids=children,
        version_date=_date(row["canonical_version_date"]),
        version_label=bill_meta["canonical_version_code"] if bill_meta else None,
        is_current=True,
        adjacency_summary=_adjacency(conn, section_id),
        provenance=_make_provenance(sources, notes=notes),
    )


# ----- get_citation_graph -----

def get_citation_graph(
    section_id: str,
    *,
    depth: int = 1,
    edge_types: list[CitationType] | None = None,
    direction: Literal["out", "in", "both"] = "both",
    max_nodes: int = 50,
) -> CitationGraph:
    conn = _db()
    # citations table is empty in v1; check that section exists then return empty graph with note
    exists = conn.execute("SELECT 1 FROM sections WHERE section_id = ?", (section_id,)).fetchone()
    if not exists:
        return CitationGraph(
            root_section_id=section_id, nodes=[], edges=[], truncated=False,
        )
    # Citation extraction is Phase 4 — return empty graph honestly
    return CitationGraph(
        root_section_id=section_id,
        nodes=[],
        edges=[],
        truncated=False,
    )


# ----- resolve_citation -----

_RE_SEC_OF_BILL = re.compile(
    r"""(?ix)
    (?:Sec\.?|Section)\s*                    # 'Sec.' or 'Section'
    (?P<sec>\d+[a-z]?)                       # section number ('3' or '3a')
    (?P<subs>(?:\([0-9a-zA-Z]+\))*)          # zero or more subdivisions, e.g. '(a)(1)'
    \s*of\s*
    (?P<billtype>H\.?\s*R\.?|S\.?|H\.?\s*J\.?\s*Res\.?|S\.?\s*J\.?\s*Res\.?|H\.?\s*Con\.?\s*Res\.?|S\.?\s*Con\.?\s*Res\.?)
    \s*(?P<num>\d+)
    (?:,?\s*(?P<congress>\d+)(?:st|nd|rd|th)?\s*Cong)?
    """,
)

_BILLTYPE_MAP = {
    "hr": "hr", "h r": "hr",
    "s": "s",
    "hjres": "hjres", "h j res": "hjres",
    "sjres": "sjres", "s j res": "sjres",
    "hconres": "hconres", "h con res": "hconres",
    "sconres": "sconres", "s con res": "sconres",
}


def _normalize_billtype(s: str) -> str | None:
    key = re.sub(r"[^a-zA-Z]+", " ", s).strip().lower()
    key = re.sub(r"\s+", " ", key)
    return _BILLTYPE_MAP.get(key) or _BILLTYPE_MAP.get(key.replace(" ", ""))


def resolve_citation(citation_string: str) -> ResolvedCitation:
    conn = _db()
    m = _RE_SEC_OF_BILL.search(citation_string)
    if not m:
        return ResolvedCitation(
            input=citation_string,
            resolved=[],
            is_ambiguous=False,
            provenance=_make_provenance(
                [f"polilabs:db@{DB_PATH}"],
                notes="No supported citation pattern matched. v1 supports 'Sec. X(a)(1) of H.R. N, Cth Cong.' style.",
            ),
        )
    sec = m.group("sec")
    subs_raw = m.group("subs") or ""
    sub_enums = re.findall(r"\(([0-9a-zA-Z]+)\)", subs_raw)
    billtype = _normalize_billtype(m.group("billtype"))
    bill_number = int(m.group("num"))
    congress_str = m.group("congress")
    congress = int(congress_str) if congress_str else None

    if billtype is None:
        return ResolvedCitation(
            input=citation_string, resolved=[], is_ambiguous=False,
            provenance=_make_provenance(
                [f"polilabs:db@{DB_PATH}"],
                notes=f"Could not normalize bill type {m.group('billtype')!r}",
            ),
        )

    # Find matching bill(s)
    if congress is not None:
        bill_rows = conn.execute(
            "SELECT bill_id FROM bills WHERE bill_type=? AND bill_number=? AND congress=?",
            (billtype, bill_number, congress),
        ).fetchall()
    else:
        bill_rows = conn.execute(
            "SELECT bill_id FROM bills WHERE bill_type=? AND bill_number=?",
            (billtype, bill_number),
        ).fetchall()

    if not bill_rows:
        return ResolvedCitation(
            input=citation_string, resolved=[], is_ambiguous=False,
            provenance=_make_provenance(
                [f"polilabs:db@{DB_PATH}"],
                notes="Bill matched citation pattern but is not in corpus",
            ),
        )

    # Build the target enum stack: section enum + subdivision enums
    enum_stack = [sec.lstrip("0") or "0"] + sub_enums
    resolved: list[ResolvedRef] = []
    for br in bill_rows:
        bid = br["bill_id"]
        # Walk sections matching the enum_stack from root
        cur_parent = None
        cur_section_id: str | None = None
        confidence = 1.0
        for level_enum in enum_stack:
            match = conn.execute(
                "SELECT section_id FROM sections WHERE bill_id=? AND "
                "((parent_section_id IS NULL AND ? IS NULL) OR parent_section_id = ?) AND "
                "(enum = ? OR enum = ?)",
                (bid, cur_parent, cur_parent, level_enum, level_enum.lstrip("0")),
            ).fetchone()
            if match is None:
                confidence *= 0.5
                cur_section_id = None
                break
            cur_section_id = match["section_id"]
            cur_parent = cur_section_id
        if cur_section_id:
            resolved.append(ResolvedRef(
                section_id=cur_section_id,
                confidence=confidence,
                interpretation_note=f"Matched bill {bid}, enum path {' > '.join(enum_stack)}",
            ))

    return ResolvedCitation(
        input=citation_string,
        resolved=resolved,
        is_ambiguous=len(resolved) > 1,
        provenance=_make_provenance([f"polilabs:db@{DB_PATH}"]),
    )


# ----- corpus_coverage -----

def corpus_coverage() -> CoverageReport:
    conn = _db()
    meta = dict(conn.execute("SELECT key, value FROM corpus_meta"))
    freshness = [
        SourceFreshness(source=r["source"], last_fetched=datetime.fromisoformat(r["last_fetched"]))
        for r in conn.execute("SELECT source, last_fetched FROM source_freshness")
    ]

    congresses = sorted({r[0] for r in conn.execute("SELECT DISTINCT congress FROM bills")})
    dates_raw = conn.execute(
        "SELECT MIN(introduced_date), MAX(introduced_date) FROM bills WHERE introduced_date IS NOT NULL"
    ).fetchone()
    drange = (_date(dates_raw[0]) or date(2023, 1, 3), _date(dates_raw[1]) or _date(dates_raw[0]) or date.today())

    tier_counts_raw = {r[0]: r[1] for r in conn.execute("SELECT tier, COUNT(*) FROM bills GROUP BY tier")}
    tier_counts: dict[Tier, int] = {
        "A": tier_counts_raw.get("A", 0),
        "B": tier_counts_raw.get("B", 0),
    }

    streams_in = [
        StreamStatus(stream=s, reason=None)
        for s in (meta.get("streams_in_scope", "legislation").split(","))
        if s
    ]
    streams_out = [
        StreamStatus(stream=s, reason=f"Reserved for post-v1 ingestion; criteria v{meta.get('criteria_version', '1.0')} excludes")
        for s in (meta.get("streams_out_of_scope", "regulatory,executive").split(","))
        if s
    ]

    known_gaps = [
        "Bill text point-in-time history not yet indexed (one canonical version per bill).",
        "Citation graph empty (Phase 4 work).",
        "Multi-source agreement scoring not yet populated (Phase 4 work).",
    ]

    return CoverageReport(
        corpus_version=meta.get("corpus_version", "unknown"),
        criteria_version=meta.get("criteria_version", "unknown"),
        last_updated=datetime.fromisoformat(meta["last_updated"]) if meta.get("last_updated") else _now_utc(),
        streams_in_scope=streams_in,
        streams_out_of_scope=streams_out,
        date_range=drange,
        congresses=congresses,
        bill_count_by_tier=tier_counts,
        source_freshness=freshness,
        known_gaps=known_gaps,
    )
