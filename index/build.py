"""Build the polilabs SQLite index from data/corpus/legislation/.

For each bill directory:
  - Read metadata.json and provenance.json
  - Parse bill.xml into hierarchical sections
  - Insert one row in `bills`, one per section, plus actions/cosponsors/subjects/versions
  - Populate FTS5 tables

The build is destructive — it drops and recreates everything. The DB is
regeneratable from the corpus files, which are the source of truth.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .parse_uslm import parse_bill_xml
from .schema import SCHEMA

CORPUS_DIR = Path("data/corpus/legislation")  # legacy AI corpus (back-compat)
CORPUS_BASE = Path("data/corpus")             # parent of all topic subdirs
INDEX_PATH = Path("data/polilabs.db")


def _iter_bill_dirs(base: Path):
    """Yield every bill directory under `base`.

    Auto-detects whether `base` is a topic directory (its immediate
    children are bill dirs with metadata.json) or the corpus root
    containing several topic subdirs. Adding a new topic is a no-op for
    the build — drop a sibling dir under data/corpus/ and re-run.
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


def _open_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()  # destructive: regenerate from scratch
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    return conn


def _insert_bill(conn: sqlite3.Connection, meta: dict, xml_format: str) -> None:
    conn.execute(
        """
        INSERT INTO bills (
            bill_id, congress, bill_type, bill_number, title, short_title,
            sponsor, introduced_date, latest_action_date, latest_action_text,
            policy_area, summary_text, tier, stream, topic, centrality_score,
            canonical_package_id, canonical_version_code, canonical_version_date,
            xml_format
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            meta["bill_id"],
            meta["congress"],
            meta["bill_type"],
            meta["bill_number"],
            meta.get("title"),
            meta.get("short_title"),
            meta.get("sponsor"),
            meta.get("introduced_date"),
            _action_date(meta.get("latest_action")),
            _action_text(meta.get("latest_action")),
            meta.get("policy_area"),
            meta.get("summary_text"),
            meta.get("tier"),
            meta.get("stream", "legislation"),
            meta.get("topic", "ai_governance"),
            meta.get("centrality_score"),
            (meta.get("canonical_version") or {}).get("package_id"),
            (meta.get("canonical_version") or {}).get("version_code"),
            (meta.get("canonical_version") or {}).get("date_issued"),
            xml_format,
        ),
    )


def _action_date(s: str | None) -> str | None:
    if not s:
        return None
    # Format from promoter: "YYYY-MM-DD: action text"
    head, _, _ = s.partition(":")
    return head.strip() or None


def _action_text(s: str | None) -> str | None:
    if not s:
        return None
    _, _, tail = s.partition(":")
    return tail.strip() or None


def _insert_versions(conn: sqlite3.Connection, meta: dict) -> None:
    bill_id = meta["bill_id"]
    for v in meta.get("versions_available", []):
        conn.execute(
            """INSERT OR IGNORE INTO bill_versions
               (package_id, bill_id, version_code, date_issued)
               VALUES (?,?,?,?)""",
            (v["package_id"], bill_id, v["version_code"], v["date_issued"]),
        )


def _insert_cosponsors(conn: sqlite3.Connection, meta: dict) -> None:
    bill_id = meta["bill_id"]
    seen: set[str] = set()
    for cs in meta.get("cosponsors", []):
        name = cs.get("fullName") or cs.get("lastName")
        if not name or name in seen:
            continue
        seen.add(name)
        conn.execute(
            """INSERT OR IGNORE INTO cosponsors
               (bill_id, name, party, state, sponsorship_date)
               VALUES (?,?,?,?,?)""",
            (bill_id, name, cs.get("party"), cs.get("state"), cs.get("sponsorshipDate")),
        )


def _insert_actions(conn: sqlite3.Connection, meta: dict) -> None:
    bill_id = meta["bill_id"]
    for i, a in enumerate(meta.get("actions", [])):
        conn.execute(
            """INSERT OR IGNORE INTO actions
               (bill_id, ordinal, action_date, action_text)
               VALUES (?,?,?,?)""",
            (bill_id, i, a.get("actionDate"), a.get("text")),
        )


def _insert_subjects(conn: sqlite3.Connection, meta: dict) -> None:
    bill_id = meta["bill_id"]
    for s in meta.get("subjects", []):
        if not s:
            continue
        conn.execute(
            "INSERT OR IGNORE INTO subjects (bill_id, subject) VALUES (?,?)",
            (bill_id, s),
        )


def _insert_sections(conn: sqlite3.Connection, rows: list) -> None:
    if not rows:
        return
    conn.executemany(
        """INSERT OR IGNORE INTO sections (
            section_id, bill_id, parent_section_id, level, enum, heading,
            text_self, text_full, canonical_citation, ordinal, xml_id
           ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        [
            (r.section_id, r.bill_id, r.parent_section_id, r.level, r.enum,
             r.heading, r.text_self, r.text_full, r.canonical_citation,
             r.ordinal, r.xml_id)
            for r in rows
        ],
    )


def _populate_fts(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM bills_fts")
    conn.execute("""
        INSERT INTO bills_fts (bill_id, topic, title, short_title, summary_text, policy_area, sponsor)
        SELECT bill_id, topic, title, short_title, summary_text, policy_area, sponsor FROM bills
    """)
    conn.execute("DELETE FROM sections_fts")
    # Carry topic onto each section row by joining on bill_id. Enables
    # `... MATCH ? AND topic = ?` against sections_fts without a follow-up
    # join (cheap because UNINDEXED in the FTS5 declaration).
    conn.execute("""
        INSERT INTO sections_fts (section_id, bill_id, topic, heading, text_full)
        SELECT s.section_id, s.bill_id, b.topic, s.heading, s.text_full
        FROM sections s JOIN bills b ON b.bill_id = s.bill_id
    """)


def _write_meta(conn: sqlite3.Connection, freshness: dict[str, str]) -> None:
    now = datetime.now(timezone.utc).isoformat()
    meta = {
        "corpus_version": "v1.0",
        "criteria_version": "v1.0",
        "last_updated": now,
        "streams_in_scope": "legislation",
        "streams_out_of_scope": "regulatory,executive",
    }
    for k, v in meta.items():
        conn.execute("INSERT OR REPLACE INTO corpus_meta (key, value) VALUES (?,?)", (k, v))
    for source, ts in freshness.items():
        conn.execute(
            "INSERT OR REPLACE INTO source_freshness (source, last_fetched) VALUES (?,?)",
            (source, ts),
        )


def build_index(
    *,
    corpus_dir: Path = CORPUS_BASE,
    db_path: Path = INDEX_PATH,
    verbose: bool = True,
) -> dict:
    conn = _open_db(db_path)
    bill_dirs = list(_iter_bill_dirs(corpus_dir))
    stats = {"bills": 0, "sections": 0, "parse_errors": 0, "format": {}}
    latest_fetched: dict[str, str] = {}

    try:
        with conn:
            for i, d in enumerate(bill_dirs):
                meta_path = d / "metadata.json"
                xml_path = d / "bill.xml"
                if not meta_path.exists() or not xml_path.exists():
                    continue
                meta = json.loads(meta_path.read_text())
                try:
                    rows, fmt = parse_bill_xml(
                        xml_path,
                        bill_id=meta["bill_id"],
                        congress=meta["congress"],
                        bill_type=meta["bill_type"],
                        bill_number=meta["bill_number"],
                    )
                except Exception as e:
                    stats["parse_errors"] += 1
                    if verbose:
                        print(f"[parse-error] {meta['bill_id']}: {type(e).__name__}: {e}")
                    continue

                _insert_bill(conn, meta, fmt)
                _insert_versions(conn, meta)
                _insert_cosponsors(conn, meta)
                _insert_actions(conn, meta)
                _insert_subjects(conn, meta)
                _insert_sections(conn, rows)

                stats["bills"] += 1
                stats["sections"] += len(rows)
                stats["format"][fmt] = stats["format"].get(fmt, 0) + 1

                # Track freshness from provenance
                prov_path = d / "provenance.json"
                if prov_path.exists():
                    prov = json.loads(prov_path.read_text())
                    ts = prov.get("fetched_at")
                    if ts:
                        for src in ("govinfo", "congress.gov"):
                            cur = latest_fetched.get(src)
                            if cur is None or ts > cur:
                                latest_fetched[src] = ts

                if verbose and (i + 1) % 25 == 0:
                    print(f"  indexed {i + 1}/{len(bill_dirs)} bills, {stats['sections']} sections so far")

            _populate_fts(conn)
            _write_meta(conn, latest_fetched)

        # Final stats query
        cur = conn.execute("SELECT COUNT(*) FROM bills")
        stats["bills_in_db"] = cur.fetchone()[0]
        cur = conn.execute("SELECT COUNT(*) FROM sections")
        stats["sections_in_db"] = cur.fetchone()[0]
        cur = conn.execute("SELECT tier, COUNT(*) FROM bills GROUP BY tier")
        stats["tier_breakdown"] = dict(cur.fetchall())

    finally:
        conn.close()

    return stats
