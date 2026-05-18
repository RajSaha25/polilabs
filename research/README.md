# research/

Background research — landscape analysis + design principles. Reading these tells you **why** polilabs makes its choices.

## Files

- **`landscape.md`** — Survey of existing tools for queryable legislative data (Congress.gov, GovInfo, Quorum, FiscalNote, Congressional Bills Project, etc.) and the gap polilabs targets. TL;DR: nobody combines (a) Congress.gov-grade citation accuracy with (b) natural-language querying and (c) the hallucination-mitigation approach validated by the Stanford RegLab study. Snapshot 2026-05-17.
- **`principles.md`** — The "four non-negotiables" that earn polilabs scholarly credibility: deterministic citation, refuse under uncertainty, verbatim-text-with-citation, and bitemporal versioning. Read this *before* arguing for a design tradeoff that violates one of them.

## Not the same as `schema_design.md`

- **`schema_design.md`** (repo root, ~7,500 words) is the **property-graph ontology** — what node and edge types exist, how versioning works, how amendment synthesis is structured. Read this if you're touching `graph/`, `api/`, or `eval/`.
- **`research/principles.md`** is the **product philosophy** — what we won't compromise on. Read this if you're debating a feature tradeoff.
- **`research/landscape.md`** is **market intelligence** — what exists, what's missing. Read this if you're scoping new features or pitching the project.

## Worth knowing

The Stanford RegLab study referenced in `principles.md` (J. Empirical Legal Studies, 2025) is the documented evidence that even commercial legal AI tools (Lexis+ AI, Westlaw AI) hallucinate at unacceptable rates for scholarly use. polilabs' anti-hallucination architecture — span-level provenance, forced retrieval, refuse-if-uncertain — is a direct response.
