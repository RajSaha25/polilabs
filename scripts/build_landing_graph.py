"""Build web-design-a/landing-graph.json — the static fixture rendered by
the landing-page ambient drift graph.

Two bills get an edge if they share ≥1 defined term whose surface form is
identical (case-insensitive, trimmed). That is the strongest semantic
signal we can pull from the property graph without paraphrase: when two
AI-governance bills both define "foundation model," they are in the same
conversation. We weight edges by the count of shared terms.

Generic terms ("Director," "Secretary," etc.) appear in nearly every bill
and would produce a uniform clique. We drop any term defined by more than
DEGREE_CAP bills — purely structural; no semantic filtering. The cutoff
is tuned to keep the graph readable (~50–200 edges).

Honest output: the fixture is exactly what the corpus contains. No
synthetic nodes, no synthetic edges. If two bills don't actually share a
term, they don't get an edge.

Usage:
    cp -R /Users/andrewdou/polilabs/data/polilabs.kuzu /tmp/landing_graph_kuzu
    /Users/andrewdou/polilabs/.venv/bin/python scripts/build_landing_graph.py

The DB is copied because the live backend keeps an exclusive lock on
the canonical file.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import kuzu

DB_PATH = "/tmp/landing_graph_kuzu"
OUT_PATH = Path(__file__).resolve().parents[1] / "web-design-a" / "landing-graph.json"

# A term defined by more than this many bills is treated as boilerplate
# (e.g. "Secretary," "Director") and excluded from edge calculation.
DEGREE_CAP = 12

# Cap node count to keep render cheap. Drop the lowest-degree bills.
MAX_NODES = 60

# Drop edges below this weight (singleton term overlaps are noise — two
# bills happening to both define "State" doesn't say they're in the
# same conversation).
MIN_EDGE_WEIGHT = 2


def short_title_from(official: str | None, bill_id: str) -> str:
    """Compact label for the node — first clause of the title or the bill id."""
    if not official:
        # bill:us/118/hr/1718 → H.R. 1718
        m = re.match(r"bill:us/(\d+)/(\w+)/(\d+)", bill_id)
        if m:
            chamber = {"hr": "H.R.", "s": "S.", "hres": "H.Res.", "sres": "S.Res.",
                       "hjres": "H.J.Res.", "sjres": "S.J.Res."}.get(m.group(2), m.group(2).upper())
            return f"{chamber} {m.group(3)}"
        return bill_id
    # Strip the "To … Act" cruft; take the first segment of the title up to
    # the first comma or period that follows a reasonable amount of text.
    text = official.strip()
    if len(text) <= 60:
        return text
    cut = re.split(r"[.,;] ", text, maxsplit=1)[0]
    if len(cut) <= 80:
        return cut
    return cut[:77].rstrip() + "…"


def main() -> int:
    db = kuzu.Database(DB_PATH, read_only=True)
    conn = kuzu.Connection(db)

    # ── pull every bill with the fields we want to display ─────────────
    # Chamber bucket per bill_type — drives node coloring on the landing.
    # House-side and Senate-side stay distinct; joint resolutions share the
    # originating chamber's bucket.
    def chamber_of(btype: str) -> str:
        bt = (btype or "").lower()
        if bt in ("hr", "hres", "hjres", "hconres"):
            return "house"
        if bt in ("s", "sres", "sjres", "sconres"):
            return "senate"
        return "other"

    bills: dict[str, dict] = {}
    res = conn.execute(
        "MATCH (b:Bill) "
        "RETURN b.bill_id, b.congress, b.bill_type, b.bill_number, "
        "       b.official_title, b.short_title, b.sponsor_display_name, "
        "       b.centrality_score"
    )
    while res.has_next():
        row = res.get_next()
        bill_id, congress, btype, bnum, official, short, sponsor, score = row
        label = short or short_title_from(official, bill_id)
        bills[bill_id] = {
            "id": bill_id,
            "label": short_title_from(label, bill_id) if not short else label[:80],
            "congress": congress,
            "chamber": chamber_of(btype),
            "ref": f"{btype.upper().replace('HR','H.R.').replace('S','S.')} {bnum}".replace("HRES","H.Res.").replace("SRES","S.Res."),
            "sponsor": sponsor or "",
            "centrality": float(score or 0.0),
        }

    print(f"loaded {len(bills)} bills", file=sys.stderr)

    # ── bills sharing a defined term (case-insensitive surface form) ───
    # DefinedTerm IDs are stamped `<bill_id>::<section_xml_id>::term/<slug>`,
    # so the bill_id is recoverable from the term's own primary key without
    # a multi-hop Section traversal (HAS_SECTION points only at top-level
    # sections; most definitions live deeper under PARENT_OF).
    res = conn.execute(
        "MATCH (t:DefinedTerm) "
        "RETURN t.defined_term_id, lower(trim(t.surface_form))"
    )
    term_to_bills: dict[str, set[str]] = defaultdict(set)
    while res.has_next():
        term_id, term = res.get_next()
        if not term or not term_id:
            continue
        # term_id like "bill:us/118/hr/10262::HXXX::term/ai"
        bid = term_id.split("::", 1)[0]
        if bid in bills:
            term_to_bills[term].add(bid)

    # Drop boilerplate terms.
    kept_terms = {t: bs for t, bs in term_to_bills.items()
                  if 2 <= len(bs) <= DEGREE_CAP}
    print(f"{len(term_to_bills)} unique terms; "
          f"{len(kept_terms)} after 2..{DEGREE_CAP} filter", file=sys.stderr)

    # ── pairwise edge weights = count of shared kept terms ─────────────
    edge_w: Counter[tuple[str, str]] = Counter()
    edge_terms: dict[tuple[str, str], list[str]] = defaultdict(list)
    for term, bs in kept_terms.items():
        bs_list = sorted(bs)
        for i, a in enumerate(bs_list):
            for b in bs_list[i + 1:]:
                key = (a, b)
                edge_w[key] += 1
                if len(edge_terms[key]) < 5:
                    edge_terms[key].append(term)

    print(f"{len(edge_w)} raw edges from shared terms", file=sys.stderr)

    # ── degree-weighted node ranking ────────────────────────────────────
    degree: Counter[str] = Counter()
    for (a, b), w in edge_w.items():
        degree[a] += w
        degree[b] += w

    # Keep the top MAX_NODES bills by (degree + centrality), then keep
    # only edges among kept nodes.
    def rank(bid: str) -> float:
        return degree.get(bid, 0) + 0.5 * bills.get(bid, {}).get("centrality", 0.0)

    ranked = sorted(bills.values(), key=lambda b: rank(b["id"]), reverse=True)
    kept_nodes = {b["id"] for b in ranked[:MAX_NODES] if degree[b["id"]] > 0}
    print(f"kept {len(kept_nodes)} nodes (those with ≥1 edge after term filter)",
          file=sys.stderr)

    nodes_out = []
    for b in ranked:
        if b["id"] not in kept_nodes:
            continue
        nodes_out.append({
            "id": b["id"],
            "label": b["label"],
            "ref": b["ref"],
            "congress": b["congress"],
            "chamber": b["chamber"],
            "sponsor": b["sponsor"],
            "degree": degree[b["id"]],
        })

    edges_out = []
    for (a, b), w in edge_w.items():
        if w < MIN_EDGE_WEIGHT:
            continue
        if a in kept_nodes and b in kept_nodes:
            edges_out.append({
                "a": a, "b": b, "w": w,
                "terms": edge_terms[(a, b)],
            })
    edges_out.sort(key=lambda e: -e["w"])

    # Drop any nodes that now have zero edges after the weight filter.
    referenced = set()
    for e in edges_out:
        referenced.add(e["a"])
        referenced.add(e["b"])
    nodes_out = [n for n in nodes_out if n["id"] in referenced]
    print(f"emitting {len(nodes_out)} nodes, {len(edges_out)} edges",
          file=sys.stderr)

    # Corpus-wide aggregates the landing page also wants to display.
    res = conn.execute("MATCH (t:DefinedTerm) RETURN count(t)")
    total_terms = res.get_next()[0]
    res = conn.execute("MATCH ()-[r:CITES_EXTERNAL]->() RETURN count(r)")
    total_cites = res.get_next()[0]
    res = conn.execute("MATCH (s:Section) RETURN count(s)")
    total_sections = res.get_next()[0]

    # ── hero subgraph: small four-node neighborhood for the landing ──
    # A center bill + one related bill (linked by shared definitions)
    # + one featured definition + one featured section. The two
    # featured items get floating description cards with their actual
    # corpus content so the visitor reads real bill text, not a
    # paraphrase. Hardcoded picks so the diagram is stable across
    # rebuilds; if any disappears from the corpus we log a warning
    # rather than silently substitute.
    HERO_CENTER = "bill:us/118/s/4664"   # Manchin, Department of Energy AI Act
    HERO_RELATED = "bill:us/118/s/4178"  # Cantwell, Future of AI Innovation Act 2024
    FEATURED_DEF = "foundation model"
    FEATURED_SECTION_HEADING = "Ensuring energy security for datacenters and computing resources"

    def get_bill(bid):
        r = conn.execute(
            "MATCH (b:Bill {bill_id: $b}) "
            "RETURN b.bill_id, b.official_title, b.short_title, "
            "       b.sponsor_display_name, b.congress, b.bill_type, b.bill_number",
            {"b": bid},
        )
        if not r.has_next():
            return None
        bid_, official, short, sponsor, bcong, btype, bnum = r.get_next()
        return {
            "id": bid_,
            "ref": f"{btype.upper().replace('HR','H.R.').replace('S','S.')} {bnum}",
            "label": short or short_title_from(official, bid_),
            "sponsor": sponsor or "",
            "congress": bcong,
        }

    center = get_bill(HERO_CENTER)
    related = get_bill(HERO_RELATED)
    hero_payload = None

    if center and related:
        # Featured definition — pull the full definition_text from the
        # corpus and clean up the leading enum prefix like "(4) ".
        def_text = None
        r = conn.execute(
            "MATCH (t:DefinedTerm) "
            "WHERE starts_with(t.defined_term_id, $b) "
            "  AND lower(trim(t.surface_form)) = $term "
            "RETURN t.definition_text",
            {"b": HERO_CENTER, "term": FEATURED_DEF},
        )
        if r.has_next():
            def_text = r.get_next()[0] or ""
            # strip leading "(N) Term" preface — leaves just the gloss
            def_text = re.sub(
                r"^\s*\(\d+\)\s*[A-Za-z][A-Za-z ]*?\s+(?=The term|means|—)",
                "", def_text,
            ).strip()

        # Featured section — heading + the lead-in sentence from text_self.
        sec_excerpt = None
        r = conn.execute(
            "MATCH (:Bill {bill_id: $b})-[:HAS_VERSION]->(:BillVersion)"
            "-[:HAS_SECTION]->(s:Section) "
            "WHERE s.heading = $h "
            "RETURN s.heading, s.text_self",
            {"b": HERO_CENTER, "h": FEATURED_SECTION_HEADING},
        )
        if r.has_next():
            heading, text_self = r.get_next()
            sec_excerpt = {
                "heading": heading,
                "text": (text_self or "").strip(),
            }

        # Detect which terms the two bills actually share — this is what
        # the unlabeled bill-to-bill edge "stands for". Stash the top
        # one or two so the diagram's hover/legend can explain the link.
        shared_terms = []
        r = conn.execute(
            "MATCH (t1:DefinedTerm) WHERE starts_with(t1.defined_term_id, $a) "
            "RETURN lower(trim(t1.surface_form))",
            {"a": HERO_CENTER},
        )
        cset = {row[0] for row in iter(lambda: r.get_next() if r.has_next() else None, None) if row and row[0]}
        r = conn.execute(
            "MATCH (t2:DefinedTerm) WHERE starts_with(t2.defined_term_id, $a) "
            "RETURN lower(trim(t2.surface_form))",
            {"a": HERO_RELATED},
        )
        rset = {row[0] for row in iter(lambda: r.get_next() if r.has_next() else None, None) if row and row[0]}
        # drop boilerplate (terms that appear in >12 bills overall)
        for t in sorted(cset & rset, key=lambda s: -len(term_to_bills.get(s, set()))):
            if 2 <= len(term_to_bills.get(t, set())) <= 12:
                shared_terms.append(t)
            if len(shared_terms) >= 3:
                break

        hero_payload = {
            "center": center,
            "related": related,
            "shared_terms": shared_terms,
            "featured_definition": {
                "term": FEATURED_DEF,
                "text": def_text,
            },
            "featured_section": sec_excerpt,
            "note": (
                "Real connections from the polilabs corpus — definitions "
                "and section text drawn verbatim from the bill XML."
            ),
        }
        print(
            f"hero: {center['ref']} ↔ {related['ref']} "
            f"(shared: {shared_terms[:3]}); "
            f"def='{FEATURED_DEF}' "
            f"section='{FEATURED_SECTION_HEADING[:30]}…'",
            file=sys.stderr,
        )
    else:
        missing = []
        if not center: missing.append(HERO_CENTER)
        if not related: missing.append(HERO_RELATED)
        print(f"WARNING: hero bill(s) missing: {missing}", file=sys.stderr)

    payload = {
        "generated_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
        "corpus": {
            "bills": len(bills),
            "sections": int(total_sections),
            "defined_terms": int(total_terms),
            "external_citations": int(total_cites),
        },
        "hero": hero_payload,
        "graph": {
            "nodes": nodes_out,
            "edges": edges_out,
        },
        "note": (
            "Edges connect bills that share at least one defined term "
            f"(surface-form match, case-insensitive). Boilerplate terms "
            f"defined by more than {DEGREE_CAP} bills are excluded. "
            "Built directly from the polilabs Kùzu graph — no synthetic edges."
        ),
    }
    OUT_PATH.write_text(json.dumps(payload, indent=2))
    print(f"wrote {OUT_PATH}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
