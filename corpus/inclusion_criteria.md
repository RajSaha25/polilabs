# AI-governance corpus — inclusion criteria (v1)

This is the source of truth for what counts as an "AI-governance" item in the v1 polilabs corpus. Code that filters candidate bills references this file; do not change criteria informally.

## Anchor keyword (required)

At least one of the following must appear in the bill text, summary, or title:

- `AI` (as a standalone token, case-insensitive — not as a substring of unrelated words)
- `artificial intelligence`
- `machine learning`

A bill that does not contain any anchor keyword is **out of scope**, regardless of how AI-relevant it appears.

## Additional in-scope terms

These do not need to be the anchor, but their presence (alongside an anchor) expands the relevance signal:

- `facial recognition`
- `generative AI` / `generative artificial intelligence`
- `frontier model`
- `automated decision systems`

## Explicitly out

- `algorithmic decision making` standalone — too distant from AI when no anchor keyword co-occurs.

## Centrality tiers

| Tier | Definition | v1 inclusion |
|---|---|---|
| **A — Primary** | The bill's main subject is AI, ML, or one of the in-scope terms. The headline, short title, or summary makes AI policy the bill's core purpose. | Include |
| **B — Substantial** | AI is a meaningful section or title of the bill but not the headline subject. e.g., an NDAA section on DoD AI use, or an appropriations rider funding AI research. The AI provisions are non-trivial. | Include, tagged Tier B |
| **C — Peripheral** | AI is mentioned in passing only — a single reference, a perfunctory mention, or a definition-only inclusion. | Exclude |

The candidate fetcher applies a centrality heuristic (anchor in title > short title > summary > body only) to rank candidates before human spot-check.

## Date range

- **From**: 2023-01-03 (start of the 118th Congress)
- **To**: present
- **Congresses included**: 118th, 119th

Rationale: the post-ChatGPT period when federal AI policy activity took off. The architecture supports earlier dates; the v1 corpus boundary is a curatorial choice, not a technical one.

## Corpus scope (v1)

| Stream | v1 status | Notes |
|---|---|---|
| `legislation` | **In scope** | Federal bills and joint/concurrent resolutions from the 118th and 119th Congresses matching the criteria above. |
| `regulatory` | **Out of v1**; tagged separately when added | Agency actions (FTC orders, NIST AI RMF, Commerce export controls, NTIA guidance, etc.). |
| `executive` | **Out of v1**; tagged separately when added | Executive Orders, presidential memoranda, OMB guidance. e.g., EO 14110, EO 14179. |

When `regulatory` and `executive` streams are added, they are stored in separate buckets and their items carry a `stream` field distinct from `legislation`. They are never silently merged into the legislation bucket.

## What this file controls

- The candidate fetcher's keyword set (Phase 1.1)
- The spot-check review CSV columns and ranking (Phase 1.2)
- Which buckets the `corpus_coverage()` API primitive reports as in-scope
- The eval-set authors' definition of "should be findable"

Changes to this file are corpus-version-bumping events. Bump the version below when you edit substantively.

**Corpus criteria version:** v1.0
