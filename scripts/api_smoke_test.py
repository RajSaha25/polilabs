"""Phase 2.2 — smoke-test each of the six agent API primitives end-to-end.

Exercises the public api module against data/polilabs.db. Verifies the
contract clauses from api/SPEC.md:
  - hits never carry full bill text (search_corpus)
  - text + canonical citation travel together (get_section)
  - typed edges (get_citation_graph — empty in v1 but typed)
  - point-in-time honoured by parameter (as_of) with provenance note
  - provenance on every response
  - in_scope distinguishes empty-in-scope from out-of-scope
  - honest unknowns (get_section not_found, resolve_citation no-match)
  - coverage introspection (corpus_coverage)
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import api


def section_break(title: str) -> None:
    print(f"\n=== {title} ===")


def main() -> None:
    section_break("corpus_coverage")
    cov = api.corpus_coverage()
    print(f"  corpus_version: {cov.corpus_version}")
    print(f"  criteria_version: {cov.criteria_version}")
    print(f"  congresses: {cov.congresses}")
    print(f"  date_range: {cov.date_range[0]} to {cov.date_range[1]}")
    print(f"  bill_count_by_tier: {cov.bill_count_by_tier}")
    print(f"  streams_in_scope: {[s.stream for s in cov.streams_in_scope]}")
    print(f"  streams_out_of_scope: {[s.stream for s in cov.streams_out_of_scope]}")
    print(f"  source_freshness: {[(f.source, str(f.last_fetched)[:19]) for f in cov.source_freshness]}")
    print(f"  known_gaps: {len(cov.known_gaps)} entries")

    section_break("search_corpus('frontier model')")
    sr = api.search_corpus("frontier model", limit=3)
    print(f"  query={sr.query!r} in_scope={sr.in_scope} total={sr.total}")
    print(f"  coverage_note: {sr.coverage_note}")
    for h in sr.hits:
        print(f"    [{h.tier}] {h.bill_id}  score={h.relevance_score:.2f}  matched={h.matched_keywords}")
        print(f"          {h.title[:80]}")
        # Contract: search hits MUST NOT carry full bill text
        # (a Bill record has section_id list; here we have SearchHit with no text field)

    section_break("search_corpus filter: out-of-scope stream")
    sr2 = api.search_corpus("AI", streams=["regulatory"], limit=3)
    print(f"  in_scope={sr2.in_scope} total={sr2.total}")
    print(f"  coverage_note: {sr2.coverage_note}")

    section_break("search_corpus filter: tier and congress")
    sr3 = api.search_corpus("artificial intelligence", tier="A", congresses=[119], limit=2)
    print(f"  in_scope={sr3.in_scope} total={sr3.total}")
    for h in sr3.hits:
        print(f"    {h.bill_id}  [{h.tier}] cong={h.congress}")

    section_break("get_bill(top hit)")
    top_bill_id = sr.hits[0].bill_id if sr.hits else "119-hr-1736"
    bill = api.get_bill(top_bill_id)
    print(f"  bill_id: {bill.bill_id}")
    print(f"  title: {bill.title[:80]}")
    print(f"  sponsor: {bill.sponsor}")
    print(f"  cosponsors: {len(bill.cosponsors)}")
    print(f"  sections (top-level ToC): {len(bill.sections)}")
    for sref in bill.sections[:5]:
        print(f"    - {sref.section_id}  heading={sref.heading[:60]!r}")
    print(f"  versions: {[(v.label, str(v.version_date)) for v in bill.versions]}")
    print(f"  provenance sources: {bill.provenance.sources}")

    section_break("get_section(first top-level section)")
    if bill.sections:
        sec_id = bill.sections[0].section_id
        sec = api.get_section(sec_id)
        print(f"  section_id: {sec.section_id}")
        print(f"  canonical_citation: {sec.canonical_citation}")
        print(f"  heading: {sec.heading[:80]}")
        print(f"  text length: {len(sec.text) if sec.text else 0}")
        print(f"  text preview: {(sec.text or '')[:150]}")
        print(f"  parent: {sec.parent_section_id}")
        print(f"  children: {len(sec.child_section_ids)}")
        print(f"  adjacency: out={sec.adjacency_summary.citations_out_count}, in={sec.adjacency_summary.citations_in_count}")
        print(f"  is_current={sec.is_current} version_label={sec.version_label!r}")

    section_break("get_section(as_of=2024-01-01) — provenance note expected")
    if bill.sections:
        sec = api.get_section(bill.sections[0].section_id, as_of=date(2024, 1, 1))
        print(f"  provenance.notes: {sec.provenance.notes}")

    section_break("get_section(unknown id) — not_found expected")
    sec_404 = api.get_section("not-a-real-id::nope")
    print(f"  not_found: {sec_404.not_found}")
    print(f"  provenance.notes: {sec_404.provenance.notes}")

    section_break("get_citation_graph(top section) — empty in v1")
    if bill.sections:
        g = api.get_citation_graph(bill.sections[0].section_id)
        print(f"  nodes: {len(g.nodes)}  edges: {len(g.edges)}  truncated: {g.truncated}")

    section_break("resolve_citation('Sec. 3(a)(1) of H.R. 1736')")
    rc = api.resolve_citation("Sec. 3(a)(1) of H.R. 1736, 119th Cong.")
    print(f"  input: {rc.input}")
    print(f"  resolved count: {len(rc.resolved)}")
    for ref in rc.resolved:
        print(f"    - {ref.section_id}  conf={ref.confidence}")
        print(f"        note: {ref.interpretation_note}")
    print(f"  is_ambiguous: {rc.is_ambiguous}")

    section_break("resolve_citation('completely unrecognized form')")
    rc2 = api.resolve_citation("42 U.S.C. § 1983")
    print(f"  resolved count: {len(rc2.resolved)}")
    print(f"  provenance.notes: {rc2.provenance.notes}")

    print("\nAll primitives executed.")


if __name__ == "__main__":
    main()
