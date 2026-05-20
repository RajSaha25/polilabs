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

# Kùzu drives the citation subsystem (PR2). The rest of the primitives
# still read from SQLite; they migrate one at a time as the graph
# spine populates. Import is best-effort so api/* still works in
# environments where kuzu isn't installed yet — get_citation_graph
# returns an honest empty-with-note response in that case.
try:
    import kuzu as _kuzu_mod
except ImportError:  # pragma: no cover
    _kuzu_mod = None

from .types import (
    AdjacencySummary,
    Amendment,
    AmendmentOperationType,
    AmendmentsResult,
    AmendmentsTargetingResult,
    Bill,
    BillAmendmentSummary,
    BillDefinitionMatch,
    BillsAmendingResult,
    BillsDefiningResult,
    BillVersion,
    CitationEdge,
    CitationGraph,
    CitationType,
    CoverageReport,
    DefinedTerm,
    DefinedTermsResult,
    DefinitionAcrossCorpus,
    DefinitionScope,
    DefinitionsAcrossCorpusResult,
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

DB_PATH = Path(os.environ.get("POLILABS_DB", "data/polilabs.db"))
KUZU_PATH = Path(os.environ.get("POLILABS_KUZU", "data/polilabs.kuzu"))

_CONN: sqlite3.Connection | None = None
_KUZU_DB = None  # type: ignore[assignment]
_KUZU_CONN = None  # type: ignore[assignment]


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


def _kuzu():
    """Lazy-open the Kùzu graph; returns the connection, or None if
    the kuzu package isn't installed or the DB hasn't been built yet."""
    global _KUZU_DB, _KUZU_CONN
    if _kuzu_mod is None:
        return None
    if _KUZU_CONN is None:
        if not KUZU_PATH.exists():
            return None
        _KUZU_DB = _kuzu_mod.Database(str(KUZU_PATH))
        _KUZU_CONN = _kuzu_mod.Connection(_KUZU_DB)
    return _KUZU_CONN


_LEGACY_BILL_RE = re.compile(r"^(\d+)-([a-z]+)-(\d+)$")

# Accepts prose forms like:
#   H.R. 1736 (119th Cong.)        -> 119-hr-1736
#   HR1736 119                     -> 119-hr-1736
#   H. J. Res. 24, 118th Congress  -> 118-hjres-24
_PROSE_BILL_RE = re.compile(
    r"""(?ix)
    ^\s*
    (?P<billtype>H\.?\s*R\.?|S\.?|H\.?\s*J\.?\s*Res\.?|S\.?\s*J\.?\s*Res\.?
                 |H\.?\s*Con\.?\s*Res\.?|S\.?\s*Con\.?\s*Res\.?)
    \s*(?P<num>\d+)
    (?:[,\s(]+(?P<congress>\d+)(?:st|nd|rd|th)?(?:\s*Cong(?:ress)?\.?)?\)?)?
    \s*$
    """,
)


def _normalize_bill_id(raw: str) -> str:
    """Coerce common bill-id forms into the canonical '119-hr-1736' form.

    Pass-through for already-canonical or URN form. For prose ('H.R. 1736
    119th Cong.'), parses and rebuilds. If the input is prose but the
    congress is missing, looks up the corpus for an unambiguous match —
    if 0 or 2+ congresses contain the bill, raises KeyError with a
    pointer message rather than silently returning empty.
    """
    s = raw.strip()
    if not s:
        raise KeyError("empty bill_id")
    if _LEGACY_BILL_RE.match(s):
        return s
    if s.startswith("bill:us/"):
        body = s[len("bill:us/"):]
        parts = body.split("/")
        if len(parts) == 3:
            return f"{parts[0]}-{parts[1]}-{parts[2]}"
    m = _PROSE_BILL_RE.match(s)
    if m is None:
        raise KeyError(
            f"bill_id {raw!r} not recognized. Expected canonical form like "
            f"'119-hr-1736' or prose like 'H.R. 1736 (119th Cong.)'."
        )
    btype = _normalize_billtype(m.group("billtype"))
    bnum = m.group("num")
    cong = m.group("congress")
    if btype is None:
        raise KeyError(f"could not parse bill type from {raw!r}")
    if cong:
        return f"{cong}-{btype}-{bnum}"
    # Congress missing — disambiguate from corpus.
    rows = _db().execute(
        "SELECT congress FROM bills WHERE bill_type=? AND bill_number=?",
        (btype, int(bnum)),
    ).fetchall()
    if len(rows) == 1:
        return f"{rows[0][0]}-{btype}-{bnum}"
    if len(rows) == 0:
        raise KeyError(
            f"bill {btype.upper()} {bnum} not found in corpus across any congress"
        )
    options = sorted(f"{r[0]}-{btype}-{bnum}" for r in rows)
    raise KeyError(
        f"bill {btype.upper()} {bnum} ambiguous across congresses; "
        f"specify one of: {options}"
    )


def _to_urn_section_id(section_id: str) -> str:
    """Translate `118-hr-5949::H42A...` → `bill:us/118/hr/5949::H42A...`.

    Kùzu stores sections under URN-style bill IDs. SQLite-backed
    primitives (get_bill, get_section) still return legacy IDs. This
    bridge lets a caller pass either form to get_citation_graph and
    have it work. URN-form inputs pass through unchanged.
    """
    if section_id.startswith("bill:") or "::" not in section_id:
        return section_id
    bid_legacy, _, xml_id = section_id.partition("::")
    m = _LEGACY_BILL_RE.match(bid_legacy)
    if not m:
        return section_id
    congress, btype, bnum = m.groups()
    return f"bill:us/{congress}/{btype}/{bnum}::{xml_id}"


def _from_urn_section_id(urn_section_id: str) -> str:
    """Inverse of `_to_urn_section_id` — used when returning section IDs to
    legacy-shaped callers. Pass through anything that's not in URN form."""
    if not urn_section_id.startswith("bill:us/"):
        return urn_section_id
    # bill:us/118/hr/5949::H42A...
    body = urn_section_id[len("bill:us/"):]
    head, sep, tail = body.partition("::")
    parts = head.split("/")
    if len(parts) != 3:
        return urn_section_id
    congress, btype, bnum = parts
    return f"{congress}-{btype}-{bnum}{sep}{tail}"


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

    # Natural-language pagination hint — agents truncate when continuation
    # is only a schema field; an explicit prose nudge routes them to the
    # right next step (paginate vs. switch to an aggregate primitive).
    if total > len(hits):
        hint = (
            f"Returned {len(hits)} of {total} matching bills. "
            f"For 'list every bill that ...' tasks, do NOT paginate "
            f"through search hits — call one of the aggregate primitives "
            f"(`find_bills_defining`, `find_bills_amending`, "
            f"`find_definitions_of`) which return the complete answer in "
            f"one call. Paginate only if you genuinely need bill-level "
            f"metadata for many bills (rare)."
        )
    elif total == 0:
        hint = "No matches. Try `corpus_coverage` to verify scope."
    else:
        hint = f"Returned all {total} matching bills (complete)."
    return SearchResults(
        hits=hits,
        total=total,
        query=query,
        coverage_note=_coverage_note_static(conn),
        in_scope=True,
        pagination_hint=hint,
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
    bill_id = _normalize_bill_id(bill_id)
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
    """Citation in/out counts for a section.

    PR2: reads from the Kùzu graph if it's available — that's where
    CITES_EXTERNAL lives. Falls back to the (empty) SQLite citations
    table if Kùzu isn't built, so the function never raises.
    """
    k = _kuzu()
    if k is not None:
        urn = _to_urn_section_id(section_id)
        # 'cites' covers CITES_EXTERNAL (USC) and CITES_INTERNAL when PR2.1
        # lands. Other CitationTypes (amends/repeals/references) come
        # online in PR4.
        out_count = 0
        in_count = 0
        try:
            r = k.execute(
                "MATCH (:Section {section_id: $sid})-[c:CITES_EXTERNAL]->() RETURN COUNT(c)",
                {"sid": urn},
            )
            if r.has_next():
                out_count = int(r.get_next()[0])
            r = k.execute(
                "MATCH ()-[c:CITES_EXTERNAL]->(:Section {section_id: $sid}) RETURN COUNT(c)",
                {"sid": urn},
            )
            if r.has_next():
                in_count = int(r.get_next()[0])
        except Exception:
            # If Kùzu errors, fall through to the SQLite path below.
            pass
        else:
            by_out: dict[CitationType, int] = {"cites": out_count} if out_count else {}
            by_in: dict[CitationType, int] = {"cites": in_count} if in_count else {}
            return AdjacencySummary(
                citations_out_count=out_count,
                citations_in_count=in_count,
                by_type_out=by_out,
                by_type_in=by_in,
            )

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
    """Typed citation graph around a section.

    PR2 scope: CITES_EXTERNAL (USC) edges, depth=1 only. The schema-design
    contract supports deeper traversals and additional edge types
    (AMENDS / repeals / references); those land with PR4 and a depth>1
    BFS extension. The accepted `section_id` may be either legacy form
    (`118-hr-5949::H42A...`) or URN form (`bill:us/118/hr/5949::H42A...`).
    """
    k = _kuzu()
    urn = _to_urn_section_id(section_id)

    if k is None:
        # Honest empty response — the graph store isn't available yet.
        return CitationGraph(
            root_section_id=section_id, nodes=[], edges=[], truncated=False,
        )

    # Confirm the section exists; if not, return an empty graph.
    r = k.execute("MATCH (s:Section {section_id: $sid}) RETURN s.section_id", {"sid": urn})
    if not r.has_next():
        return CitationGraph(
            root_section_id=section_id, nodes=[], edges=[], truncated=False,
        )

    # The caller's edge-type filter is applied post-hoc. PR2 only
    # populates CITES_EXTERNAL, so `cites` is the only type that can
    # appear in the response today.
    type_filter = set(edge_types) if edge_types else None

    nodes: dict[str, SectionRef] = {}
    edges: list[CitationEdge] = []
    truncated = False
    edge_prov = _make_provenance(
        sources=["polilabs:kuzu/CITES_EXTERNAL"],
        notes="derivation=mechanical, source=USLM <external-xref>",
    )

    def _add_target(target_id: str, citation: str) -> SectionRef:
        # Synthetic SectionRef for a StatuteSection target. The schema
        # has a distinct StatuteSection node type; the CitationGraph
        # response shape doesn't yet — synthesizing here keeps the
        # existing API stable. A schema-faithful response (separate
        # statute_nodes list) is a candidate post-PR follow-up.
        if target_id not in nodes:
            nodes[target_id] = SectionRef(
                section_id=target_id,
                bill_id="",
                heading=citation,
                parent_section_id=None,
                version_count=0,
            )
        return nodes[target_id]

    # Root node (the queried section itself)
    root_r = k.execute(
        "MATCH (s:Section {section_id: $sid}) "
        "RETURN s.section_id, s.heading, s.version_id",
        {"sid": urn},
    )
    if root_r.has_next():
        rs, rh, rv = root_r.get_next()
        nodes[rs] = SectionRef(
            section_id=rs, bill_id=rv.split("@")[0] if rv else "",
            heading=rh or "", parent_section_id=None, version_count=1,
        )

    # Outbound: Section → StatuteSection
    if direction in ("out", "both") and (type_filter is None or "cites" in type_filter):
        r = k.execute(
            "MATCH (:Section {section_id: $sid})-[c:CITES_EXTERNAL]->(t:StatuteSection) "
            "RETURN t.statute_section_id, t.canonical_citation, c.raw_text "
            "LIMIT $lim",
            {"sid": urn, "lim": max_nodes},
        )
        out_rows = []
        while r.has_next():
            out_rows.append(r.get_next())
        if len(out_rows) == max_nodes:
            truncated = True
        for tid, tcit, raw in out_rows:
            _add_target(tid, tcit or tid)
            edges.append(CitationEdge(
                source_id=urn, target_id=tid, type="cites", provenance=edge_prov,
            ))

    # Inbound: ? → Section (other sections citing THIS section). v1
    # corpus has no Section→Section citations yet (PR2.1) — but the
    # query is included so the API behaves correctly once they land.
    if direction in ("in", "both") and (type_filter is None or "cites" in type_filter):
        r = k.execute(
            "MATCH (src:Section)-[c:CITES_INTERNAL]->(:Section {section_id: $sid}) "
            "RETURN src.section_id, src.heading, c.raw_text "
            "LIMIT $lim",
            {"sid": urn, "lim": max_nodes},
        )
        while r.has_next():
            src_id, src_heading, raw = r.get_next()
            if src_id not in nodes:
                nodes[src_id] = SectionRef(
                    section_id=src_id, bill_id="",
                    heading=src_heading or "", parent_section_id=None,
                    version_count=1,
                )
            edges.append(CitationEdge(
                source_id=src_id, target_id=urn, type="cites", provenance=edge_prov,
            ))

    return CitationGraph(
        root_section_id=section_id,
        nodes=list(nodes.values()),
        edges=edges,
        truncated=truncated,
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
        "USLM <ref href='...'> citations from 2 USLM bills not yet extracted (PR2.1).",
        "Public Law (74) and CITES_INTERNAL citations not yet extracted (PR2.1).",
        "Definition use-site resolution (RESOLVED_TO / UnresolvedTermUse) not yet wired (PR3.1).",
        "AmendmentOperation extraction not yet wired (PR4).",
        "Multi-source agreement scoring not yet populated.",
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


# ----- get_defined_terms -----

_URN_BILL_RE = re.compile(r"^bill:us/(\d+)/([a-z]+)/(\d+)$")


def _normalize_statute_id(raw: str) -> str:
    """Coerce 'statute:us/usc/15/9401' | '15/9401' | '15 U.S.C. 9401' |
    '15 USC § 9401' all to the URN form."""
    sid = raw.strip()
    if sid.startswith("statute:"):
        return sid
    if "/" in sid and re.match(r"^\d+/", sid):
        return f"statute:us/usc/{sid}"
    m = re.match(
        r"^(?P<title>\d+)\s*U\.?\s*S\.?\s*C\.?\s*[§\.]?\s*(?P<section>\S+)$",
        sid, re.IGNORECASE,
    )
    if m:
        return f"statute:us/usc/{m.group('title')}/{m.group('section')}"
    return sid  # pass-through; caller's query will return empty


def _to_urn_bill_id(bill_id: str) -> str:
    """Translate legacy bill_id like '119-hr-1736' to URN form."""
    if bill_id.startswith("bill:"):
        return bill_id
    m = re.match(r"^(\d+)-([a-z]+)-(\d+)$", bill_id)
    if not m:
        return bill_id
    congress, btype, bnum = m.groups()
    return f"bill:us/{congress}/{btype}/{bnum}"


def get_defined_terms(bill_id: str) -> DefinedTermsResult:
    """All DefinedTerm nodes scoped under a given bill.

    Returns every term defined in the bill's Definitions section(s),
    each with its definition text, type (direct vs. by_reference), and
    by-reference target (USC section URN + canonical citation) when
    applicable. Pass either legacy ('119-hr-1736') or URN
    ('bill:us/119/hr/1736') bill IDs.
    """
    bill_id = _normalize_bill_id(bill_id)
    k = _kuzu()
    if k is None:
        return DefinedTermsResult(
            bill_id=bill_id, terms=[],
            coverage_note="graph store unavailable; run scripts/build_kuzu_index.py",
        )

    urn_bill = _to_urn_bill_id(bill_id)
    legacy_bill = _from_urn_section_id(urn_bill + "::").rstrip("::") if urn_bill.startswith("bill:") else bill_id

    # A DefinedTerm stores its defining section's id, and that id is the
    # bill's URN section prefix + a hash — so a prefix scan finds the
    # bill's terms directly. An unbounded HAS_SECTION|PARENT_OF* walk
    # measured ~5 s per bill; this prefix scan is ~5 ms, same results.
    cypher = """
    MATCH (d:DefinedTerm)
    WHERE starts_with(d.defining_section_id, $prefix)
    OPTIONAL MATCH (s:Section {section_id: d.defining_section_id})
    OPTIONAL MATCH (d)-[:BY_REFERENCE]->(t:StatuteSection)
    RETURN d.defined_term_id, d.surface_form, d.scope, d.definition_type,
           d.definition_text, d.defining_section_id, s.canonical_citation,
           t.statute_section_id, t.canonical_citation
    ORDER BY d.surface_form
    """
    r = k.execute(cypher, {"prefix": urn_bill + "::"})

    out_terms: list[DefinedTerm] = []
    seen: set[str] = set()
    while r.has_next():
        (dtid, surface, scope, dtype, dtext,
         defining_sid_urn, defining_citation,
         br_target_sid, br_target_citation) = r.get_next()
        if dtid in seen:
            continue
        seen.add(dtid)
        out_terms.append(DefinedTerm(
            defined_term_id=dtid,
            surface_form=surface,
            bill_id=legacy_bill if not bill_id.startswith("bill:") else urn_bill,
            defining_section_id=_from_urn_section_id(defining_sid_urn),
            defining_section_citation=defining_citation or "",
            scope=scope or "section_local",  # type: ignore[arg-type]
            definition_type=dtype or "direct",  # type: ignore[arg-type]
            definition_text=dtext or "",
            by_reference_target_id=br_target_sid,
            by_reference_target_citation=br_target_citation,
            provenance=_make_provenance(
                sources=[f"polilabs:kuzu/DefinedTerm({dtid})"],
                notes="derivation=mechanical, source=Definitions container in bill XML",
            ),
        ))

    direct_n = sum(1 for t in out_terms if t.definition_type == "direct")
    by_ref_n = sum(1 for t in out_terms if t.definition_type == "by_reference")
    note = (f"{len(out_terms)} defined terms "
            f"({direct_n} direct, {by_ref_n} by-reference) "
            f"from bill {urn_bill}")
    return DefinedTermsResult(bill_id=bill_id, terms=out_terms, coverage_note=note)


# ----- get_amendments / get_amendments_targeting -----

def _amendment_from_row(
    amendment_id: str,
    source_section_id_urn: str,
    source_citation: str,
    operation_type: str,
    operation_text: str,
    target_statute_section_id: str | None,
    target_canonical: str | None,
    target_locator_json: str,
    before_text: str | None,
    after_text: str,
    target_text_unverified: bool,
) -> Amendment:
    return Amendment(
        amendment_id=amendment_id,
        source_section_id=_from_urn_section_id(source_section_id_urn),
        source_section_citation=source_citation or "",
        operation_type=operation_type or "other",  # type: ignore[arg-type]
        operation_text=operation_text or "",
        target_statute_section_id=target_statute_section_id,
        target_canonical_citation=target_canonical,
        target_locator_json=target_locator_json or "{}",
        before_text=before_text,
        after_text=after_text or "",
        target_text_unverified=bool(target_text_unverified),
        provenance=_make_provenance(
            sources=[f"polilabs:kuzu/AmendmentOperation({amendment_id})"],
            notes=(
                "derivation=mechanical, source=<quoted-block> in bill XML; "
                "target_text_unverified=True until OLRC USC ingestion"
            ),
        ),
    )


def get_amendments(bill_id: str) -> AmendmentsResult:
    """Every AmendmentOperation issued by sections of a given bill.

    Answers "what does this bill change about existing law?" — design
    doc Q1. Each Amendment carries the operation type, the target USC
    citation (when resolved), and the before/after text payloads.
    target_text_unverified is True in v1 because we do not yet ingest
    OLRC USC text; downstream EnactmentVersion synthesis will use that
    flag to surface ConflictNote markers.
    """
    bill_id = _normalize_bill_id(bill_id)
    k = _kuzu()
    if k is None:
        return AmendmentsResult(
            bill_id=bill_id, amendments=[],
            coverage_note="graph store unavailable; run scripts/build_kuzu_index.py",
        )

    urn_bill = _to_urn_bill_id(bill_id)
    # An AmendmentOperation stores its source section's id, and that id
    # is the bill's URN section prefix + a hash — so a prefix scan finds
    # the bill's operations directly. An unbounded HAS_SECTION|PARENT_OF*
    # walk measured ~5 s per bill; this prefix scan is ~5 ms, same rows.
    cypher = """
    MATCH (a:AmendmentOperation)
    WHERE starts_with(a.source_section_id, $prefix)
    OPTIONAL MATCH (s:Section {section_id: a.source_section_id})
    OPTIONAL MATCH (a)-[:TARGETS]->(t:StatuteSection)
    RETURN a.amendment_id, a.source_section_id, s.canonical_citation,
           a.operation_type, a.target_locator_json,
           a.before_text, a.after_text, a.target_text_unverified,
           t.statute_section_id, t.canonical_citation
    ORDER BY a.source_section_id, a.amendment_id
    """
    r = k.execute(cypher, {"prefix": urn_bill + "::"})
    amends: list[Amendment] = []
    while r.has_next():
        (aid, src_sid_urn, src_cite, op, locator,
         before, after, unverified,
         tgt_sid, tgt_canon) = r.get_next()
        amends.append(_amendment_from_row(
            amendment_id=aid, source_section_id_urn=src_sid_urn,
            source_citation=src_cite, operation_type=op,
            operation_text="",  # not stored as a node prop in v1 schema
            target_statute_section_id=tgt_sid,
            target_canonical=tgt_canon,
            target_locator_json=locator,
            before_text=before, after_text=after,
            target_text_unverified=unverified,
        ))

    note = (f"{len(amends)} amendment operations from bill {urn_bill}; "
            f"target_text_unverified=true (USC not yet ingested — synthesis "
            f"queries will return ConflictNote markers when verification runs)")
    return AmendmentsResult(bill_id=bill_id, amendments=amends, coverage_note=note)


def get_amendments_targeting(statute_section_id: str) -> AmendmentsTargetingResult:
    """All amendments in the corpus that target a given USC section.

    Answers "what other bills this session amend the same statute?" —
    design doc Q2. Accept either the URN form
    ('statute:us/usc/5/552') or a short '15/9401' / '15 U.S.C. 9401'
    style; this helper normalizes.
    """
    k = _kuzu()
    if k is None:
        return AmendmentsTargetingResult(
            statute_section_id=statute_section_id, statute_canonical="",
            amendments=[], coverage_note="graph store unavailable",
        )
    sid = _normalize_statute_id(statute_section_id)
    cypher = """
    MATCH (a:AmendmentOperation)-[:TARGETS]->(t:StatuteSection {statute_section_id: $sid})
    MATCH (s:Section)-[:AMENDS]->(a)
    RETURN a.amendment_id, s.section_id, s.canonical_citation,
           a.operation_type, a.target_locator_json,
           a.before_text, a.after_text, a.target_text_unverified,
           t.statute_section_id, t.canonical_citation
    ORDER BY s.section_id, a.amendment_id
    """
    r = k.execute(cypher, {"sid": sid})
    amends: list[Amendment] = []
    statute_canon = sid
    while r.has_next():
        (aid, src_sid_urn, src_cite, op, locator,
         before, after, unverified,
         tgt_sid, tgt_canon) = r.get_next()
        statute_canon = tgt_canon or sid
        amends.append(_amendment_from_row(
            amendment_id=aid, source_section_id_urn=src_sid_urn,
            source_citation=src_cite, operation_type=op,
            operation_text="",
            target_statute_section_id=tgt_sid,
            target_canonical=tgt_canon,
            target_locator_json=locator,
            before_text=before, after_text=after,
            target_text_unverified=unverified,
        ))

    bills_touched = len({a.source_section_id.split("::")[0] for a in amends})
    note = (f"{len(amends)} amendment operations from {bills_touched} bill(s) "
            f"target {statute_canon}; target_text_unverified=true (synthesis "
            f"will surface ConflictNote markers when USC ingestion runs)")
    return AmendmentsTargetingResult(
        statute_section_id=sid, statute_canonical=statute_canon,
        amendments=amends, coverage_note=note,
    )


# ----- aggregate primitives (eliminate N+1 patterns) -----
#
# These collapse "search → loop drill-in → aggregate" agent workflows
# into single Cypher queries. The eval-driven motivation: agents
# systematically truncate at 10-20 sequential tool calls (per BFCL v4
# and Anthropic's tool-design guidance), so exhaustive-list queries
# fail when modeled as search+loop. Each primitive here is one server-
# side join over the graph.


def find_bills_defining(
    term: str,
    *,
    definition_type: DefinitionType | None = None,
    by_reference_to: str | None = None,
    also_match: list[str] | None = None,
) -> BillsDefiningResult:
    """Every bill in the corpus that formally defines a term.

    `term` is matched case-insensitively on DefinedTerm.surface_form
    (exact match — does not pull "artificial intelligence system" when
    the agent asks for "artificial intelligence").

    Optional filters:
      - `definition_type='direct'` — bill defines the term with its own
        text; `'by_reference'` — bill defers to another statute.
      - `by_reference_to='15 U.S.C. 9401'` — only bills whose definition
        cross-references a specific USC section. Accepts URN, slash, or
        prose form. Implies `definition_type='by_reference'`.
      - `also_match=['AI']` — additional surface forms to OR into the
        match. Useful because bills routinely define abbreviations
        ('AI', 'GAI') as shorthand for the full term — pass both in one
        call rather than re-querying.

    Replaces the search_corpus → loop get_defined_terms pattern that
    forces 50+ sequential tool calls on the agent.
    """
    k = _kuzu()
    if k is None:
        return BillsDefiningResult(
            term=term, matches=[], total=0,
            coverage_note="graph store unavailable; run scripts/build_kuzu_index.py",
        )

    # WHERE on the primary MATCH must come BEFORE OPTIONAL MATCH —
    # Cypher binds a trailing WHERE to its nearest preceding (OPTIONAL)
    # MATCH, which would silently no-op the surface_form filter.
    all_terms = [term] + (also_match or [])
    primary_where = [
        "toLower(d.surface_form) IN [" +
        ", ".join(f"toLower($term_{i})" for i in range(len(all_terms))) +
        "]"
    ]
    params: dict = {f"term_{i}": t for i, t in enumerate(all_terms)}
    if by_reference_to:
        # Implies by_reference; also requires the join.
        definition_type = "by_reference"
        params["statute_sid"] = _normalize_statute_id(by_reference_to)
    if definition_type:
        primary_where.append("d.definition_type = $deftype")
        params["deftype"] = definition_type

    if by_reference_to:
        # Inner-join on StatuteSection when the caller asked for a
        # specific target — turns OPTIONAL into required.
        cypher = f"""
        MATCH (b:Bill)-[:HAS_VERSION]->(:BillVersion)
              -[:HAS_SECTION|PARENT_OF*]->(s:Section)-[:DEFINES]->(d:DefinedTerm)
              -[:BY_REFERENCE]->(t:StatuteSection {{statute_section_id: $statute_sid}})
        WHERE {' AND '.join(primary_where)}
        RETURN DISTINCT b.bill_id, b.short_title, b.official_title, b.congress,
               d.surface_form, d.defining_section_id, s.canonical_citation,
               d.definition_type, t.statute_section_id, t.canonical_citation
        ORDER BY b.congress, b.bill_id
        """
    else:
        cypher = f"""
        MATCH (b:Bill)-[:HAS_VERSION]->(:BillVersion)
              -[:HAS_SECTION|PARENT_OF*]->(s:Section)-[:DEFINES]->(d:DefinedTerm)
        WHERE {' AND '.join(primary_where)}
        OPTIONAL MATCH (d)-[:BY_REFERENCE]->(t:StatuteSection)
        RETURN DISTINCT b.bill_id, b.short_title, b.official_title, b.congress,
               d.surface_form, d.defining_section_id, s.canonical_citation,
               d.definition_type, t.statute_section_id, t.canonical_citation
        ORDER BY b.congress, b.bill_id
        """
    r = k.execute(cypher, params)
    matches: list[BillDefinitionMatch] = []
    while r.has_next():
        (bid_urn, short_title, title, congress, surface, defining_sid_urn,
         defining_citation, dtype, br_target, br_target_citation) = r.get_next()
        matches.append(BillDefinitionMatch(
            bill_id=_from_urn_section_id(bid_urn + "::").rstrip("::"),
            bill_short_title=short_title,
            bill_title=title or "",
            congress=congress,
            surface_form=surface,
            defining_section_id=_from_urn_section_id(defining_sid_urn),
            defining_section_citation=defining_citation or "",
            definition_type=dtype,  # type: ignore[arg-type]
            by_reference_target_id=br_target,
            by_reference_target_citation=br_target_citation,
        ))

    filter_desc = []
    if definition_type:
        filter_desc.append(f"definition_type={definition_type!r}")
    if by_reference_to:
        filter_desc.append(f"by_reference_to={by_reference_to!r}")
    fdesc = f" with {', '.join(filter_desc)}" if filter_desc else ""
    note = (
        f"{len(matches)} bill(s) define {term!r}{fdesc}. "
        f"This is the complete answer — no pagination needed."
    )
    return BillsDefiningResult(
        term=term, matches=matches, total=len(matches), coverage_note=note,
    )


def find_bills_amending(statute_section_id: str) -> BillsAmendingResult:
    """Per-bill rollup of every bill that amends a given USC section.

    Compact response: one row per bill, with operation count + distinct
    operation types. Use this for "which bills amend 15 U.S.C. 9401"
    questions; use `get_amendments_targeting` when you need the
    operation-level detail (before/after text).
    """
    k = _kuzu()
    if k is None:
        return BillsAmendingResult(
            statute_section_id=statute_section_id, statute_canonical="",
            bills=[], total=0, coverage_note="graph store unavailable",
        )
    sid = _normalize_statute_id(statute_section_id)
    cypher = """
    MATCH (b:Bill)-[:HAS_VERSION]->(:BillVersion)
          -[:HAS_SECTION|PARENT_OF*]->(:Section)-[:AMENDS]->(a:AmendmentOperation)
          -[:TARGETS]->(t:StatuteSection {statute_section_id: $sid})
    RETURN b.bill_id, b.short_title, b.official_title, b.congress,
           COUNT(DISTINCT a) AS n_ops,
           COLLECT(DISTINCT a.operation_type) AS op_types,
           t.canonical_citation
    ORDER BY n_ops DESC, b.bill_id
    """
    r = k.execute(cypher, {"sid": sid})
    bills: list[BillAmendmentSummary] = []
    statute_canon = sid
    while r.has_next():
        bid_urn, short_title, title, congress, n_ops, op_types, canon = r.get_next()
        statute_canon = canon or sid
        bills.append(BillAmendmentSummary(
            bill_id=_from_urn_section_id(bid_urn + "::").rstrip("::"),
            bill_short_title=short_title,
            bill_title=title or "",
            congress=congress,
            n_operations=int(n_ops),
            operation_types=sorted(set(op_types)),  # type: ignore[arg-type]
        ))
    note = (
        f"{len(bills)} bill(s) amend {statute_canon}. "
        f"This is the complete answer — no pagination needed. "
        f"Call get_amendments_targeting for operation-level detail."
    )
    return BillsAmendingResult(
        statute_section_id=sid, statute_canonical=statute_canon,
        bills=bills, total=len(bills), coverage_note=note,
    )


def find_definitions_of(term: str) -> DefinitionsAcrossCorpusResult:
    """Every bill's take on a single term, side by side.

    Returns the definition text (verbatim), the definition type (direct
    vs by_reference), and the by-reference target (when applicable) for
    every bill in the corpus that defines `term`. Use this to compare
    cross-bill consensus / divergence on a term like 'AI', 'frontier
    model', 'covered entity'. Case-insensitive exact match on
    surface_form.
    """
    k = _kuzu()
    if k is None:
        return DefinitionsAcrossCorpusResult(
            term=term, definitions=[], total=0,
            direct_count=0, by_reference_count=0,
            coverage_note="graph store unavailable",
        )
    # WHERE before OPTIONAL MATCH so the filter actually applies.
    cypher = """
    MATCH (b:Bill)-[:HAS_VERSION]->(:BillVersion)
          -[:HAS_SECTION|PARENT_OF*]->(s:Section)-[:DEFINES]->(d:DefinedTerm)
    WHERE toLower(d.surface_form) = toLower($term)
    OPTIONAL MATCH (d)-[:BY_REFERENCE]->(t:StatuteSection)
    RETURN DISTINCT b.bill_id, b.short_title, b.congress,
           s.canonical_citation, d.definition_type, d.definition_text,
           t.canonical_citation
    ORDER BY b.congress, b.bill_id
    """
    r = k.execute(cypher, {"term": term})
    defs: list[DefinitionAcrossCorpus] = []
    direct = by_ref = 0
    while r.has_next():
        (bid_urn, short_title, congress, defining_citation,
         dtype, dtext, br_target_citation) = r.get_next()
        if dtype == "direct":
            direct += 1
        elif dtype == "by_reference":
            by_ref += 1
        defs.append(DefinitionAcrossCorpus(
            bill_id=_from_urn_section_id(bid_urn + "::").rstrip("::"),
            bill_short_title=short_title,
            congress=congress,
            defining_section_citation=defining_citation or "",
            definition_type=dtype,  # type: ignore[arg-type]
            definition_text=dtext or "",
            by_reference_target_citation=br_target_citation,
        ))
    note = (
        f"{len(defs)} bill(s) define {term!r} ({direct} direct, {by_ref} by_reference). "
        f"This is the complete answer — no pagination needed."
    )
    return DefinitionsAcrossCorpusResult(
        term=term, definitions=defs, total=len(defs),
        direct_count=direct, by_reference_count=by_ref, coverage_note=note,
    )
