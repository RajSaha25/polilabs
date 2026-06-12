"""Load the universe artifacts (data/universe/bills_*.jsonl.gz, plus
optional rollcalls_*.jsonl.gz) into the SQLite index.

Called from index.build.build_index() after the curated-corpus pass, so
`in_corpus` can be set by joining against the bills table. Also builds
the bill_aliases table and universe_fts from every title variant
BILLSTATUS knows — the popular-name resolution layer.
"""
from __future__ import annotations

import gzip
import json
import re
import sqlite3
from pathlib import Path

UNIVERSE_DIR = Path("data/universe")

_YEAR_SUFFIX = re.compile(r"\s+of\s+(19|20)\d\d$")
_PUNCT = re.compile(r"[^\w\s]")
_WS = re.compile(r"\s+")


def normalize_alias(s: str) -> str:
    """Normalization contract for alias lookup. Mirror this EXACTLY at
    query time (api/_impl.py::lookup_bill) or lookups will miss.

    lowercase -> strip punctuation -> collapse whitespace -> drop a
    leading 'the ' -> drop a trailing 'of YYYY'.
    """
    s = s.lower()
    s = _PUNCT.sub(" ", s)
    s = _WS.sub(" ", s).strip()
    if s.startswith("the "):
        s = s[4:]
    s = _YEAR_SUFFIX.sub("", s)
    return s


def _alias_variants(title: str) -> set[str]:
    """A title contributes its normalized form; nothing fancier. The
    year-suffix drop already merges 'CHIPS Act of 2022' with 'CHIPS Act'."""
    n = normalize_alias(title)
    return {n} if len(n) >= 4 else set()


def load_universe(conn: sqlite3.Connection, *, verbose: bool = True) -> dict:
    stats = {"universe_bills": 0, "aliases": 0, "universe_votes": 0, "files": 0}
    bill_files = sorted(UNIVERSE_DIR.glob("bills_*.jsonl.gz"))
    if not bill_files:
        if verbose:
            print("[universe] no data/universe/bills_*.jsonl.gz found — skipping "
                  "(run scripts/build_universe.py)")
        return stats

    corpus_bill_ids = {r[0] for r in conn.execute("SELECT bill_id FROM bills")}

    alias_rows: list[tuple[str, str, str, str]] = []
    fts_rows: list[tuple[str, str, str]] = []

    for path in bill_files:
        stats["files"] += 1
        with gzip.open(path, "rt") as f:
            for line in f:
                rec = json.loads(line)
                bid = rec["bill_id"]
                sponsor = rec.get("sponsor") or {}
                cc = rec.get("cosponsor_counts") or {}
                la = rec.get("latest_action") or {}
                out = rec.get("outcome") or {}
                conn.execute(
                    """INSERT OR REPLACE INTO universe_bills (
                        bill_id, congress, bill_type, bill_number, title,
                        introduced_date, origin_chamber, policy_area,
                        sponsor_name, sponsor_party, sponsor_state, sponsor_bioguide,
                        cosponsors_d, cosponsors_r, cosponsors_i, cosponsors_total,
                        latest_action_date, latest_action_text,
                        outcome, public_law, outcome_events, vote_refs, in_corpus
                       ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        bid, rec["congress"], rec["bill_type"], rec["bill_number"],
                        rec.get("title"), rec.get("introduced_date"),
                        rec.get("origin_chamber"), rec.get("policy_area"),
                        sponsor.get("fullName"), sponsor.get("party"),
                        sponsor.get("state"), sponsor.get("bioguideId"),
                        cc.get("D", 0), cc.get("R", 0), cc.get("I", 0), cc.get("total", 0),
                        la.get("actionDate"), la.get("text"),
                        out.get("outcome"), out.get("public_law"),
                        json.dumps(out.get("events") or []),
                        json.dumps(rec.get("vote_refs") or []),
                        1 if bid in corpus_bill_ids else 0,
                    ),
                )
                stats["universe_bills"] += 1

                titles = set(rec.get("all_titles") or [])
                if rec.get("title"):
                    titles.add(rec["title"])
                norms: set[str] = set()
                for t in titles:
                    for n in _alias_variants(t):
                        if n not in norms:
                            norms.add(n)
                            alias_rows.append((n, t, bid, "billstatus_titles"))
                fts_rows.append((bid, rec.get("title") or "", " | ".join(sorted(titles))))

    # OLRC Popular Name Table entries join on public_law. Appended after
    # the BILLSTATUS rows, so PRIMARY KEY de-dup keeps the BILLSTATUS
    # surface form when both sources know the same normalized name; the
    # PNT contributes only names BILLSTATUS lacks.
    pnt_path = UNIVERSE_DIR / "popular_names.json"
    if pnt_path.exists():
        pl_to_bill = dict(conn.execute(
            "SELECT public_law, bill_id FROM universe_bills WHERE public_law IS NOT NULL"
        ))
        pnt_added = 0
        for entry in json.loads(pnt_path.read_text()):
            bid = pl_to_bill.get(entry["public_law"])
            if not bid:
                continue
            for n in _alias_variants(entry["name"]):
                alias_rows.append((n, entry["name"], bid, "olrc_popular_names"))
                pnt_added += 1
        stats["pnt_aliases"] = pnt_added

    conn.executemany(
        "INSERT OR IGNORE INTO bill_aliases (alias_norm, alias, bill_id, source) VALUES (?,?,?,?)",
        alias_rows,
    )
    stats["aliases"] = len(alias_rows)
    conn.execute("DELETE FROM universe_fts")
    conn.executemany(
        "INSERT INTO universe_fts (bill_id, title, aliases) VALUES (?,?,?)",
        fts_rows,
    )

    stats["universe_votes"] = _load_rollcalls(conn)

    if verbose:
        print(f"[universe] {stats['universe_bills']} bills, {stats['aliases']} aliases, "
              f"{stats['universe_votes']} votes from {stats['files']} file(s)")
    return stats


def _load_rollcalls(conn: sqlite3.Connection) -> int:
    n = 0
    for path in sorted(UNIVERSE_DIR.glob("rollcalls_*.jsonl.gz")):
        with gzip.open(path, "rt") as f:
            for line in f:
                v = json.loads(line)
                conn.execute(
                    """INSERT OR REPLACE INTO universe_votes (
                        vote_id, bill_id, chamber, congress, session, roll_number,
                        date, question, result, vote_type, yea_total, nay_total,
                        dem_yea, dem_nay, rep_yea, rep_nay,
                        bipartisan_support, bipartisan_label, source_url
                       ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        v["vote_id"], v["bill_id"], v["chamber"], v["congress"],
                        v["session"], v["roll_number"], v.get("date"),
                        v.get("question"), v.get("result"), v["vote_type"],
                        v["yea_total"], v["nay_total"],
                        v.get("dem_yea"), v.get("dem_nay"),
                        v.get("rep_yea"), v.get("rep_nay"),
                        v.get("bipartisan_support"), v.get("bipartisan_label"),
                        v["source_url"],
                    ),
                )
                n += 1
    # Final passage-class metrics onto universe_bills (latest passage vote).
    conn.execute("""
        UPDATE universe_bills SET
            bipartisan_support = (
                SELECT v.bipartisan_support FROM universe_votes v
                WHERE v.bill_id = universe_bills.bill_id AND v.vote_type = 'passage'
                  AND v.bipartisan_support IS NOT NULL
                ORDER BY v.date DESC LIMIT 1),
            bipartisan_label = (
                SELECT v.bipartisan_label FROM universe_votes v
                WHERE v.bill_id = universe_bills.bill_id AND v.vote_type = 'passage'
                  AND v.bipartisan_support IS NOT NULL
                ORDER BY v.date DESC LIMIT 1)
        WHERE EXISTS (
            SELECT 1 FROM universe_votes v
            WHERE v.bill_id = universe_bills.bill_id AND v.vote_type = 'passage')
    """)
    return n
