# Principles: How polilabs earns credibility

The polilabs thesis is that scholars need a tool that does what Lexis+ AI and Westlaw AI failed to do (Stanford RegLab study, 2024 / J. Empirical Legal Studies, 2025): answer questions about legislation without hallucinating, with citations a scholar can defend.

That credibility is not a marketing claim. It is a set of engineering and process choices, each of which is uncomfortable enough that competitors skip them. This document is the north star.

## The four non-negotiables

### 1. Deterministic citation

Every answer must carry:
- The exact bill text span quoted or paraphrased (verbatim).
- The stable bill ID: `<congress>-<chamber>-<billnumber>-<version>`. Example: `119-HR-4249-IH`.
- A copy-paste citation formatted for the scholar's chosen style (Bluebook by default, with Chicago + APA + MLA options).
- The Congress.gov URL pointing to the cited section.

No answer ships without all four. If we cannot produce all four, we surface a refusal (see #2), not a degraded answer.

### 2. Refuse under uncertainty

If retrieval returns no span above a confidence threshold, the system says so. It does not fall back to its training-memory understanding of what the bill probably says.

Concretely:
- Calibrate a confidence threshold against the eval set.
- When below threshold, return: "No high-confidence match in the corpus. Closest candidates: [list]. Refine your query or check these directly."
- Never paraphrase from training memory. Never invent a section number. Never hedge with "the bill likely says..."

The cost of a refusal is low (the user re-queries). The cost of a confident wrong answer is the entire project's credibility.

### 3. Public hallucination eval

Following the Stanford RegLab methodology (Magesh et al., "Hallucination-Free? Assessing the Reliability of Leading AI Legal Research Tools"):
- 200-300 pre-registered open-ended queries spanning bill-text questions, sponsorship/status questions, cross-bill comparisons, and historical lookups.
- Each query has a hand-verified ground-truth answer with a hand-verified citation.
- Hallucination, accuracy, refusal, and incomplete rates published as numbers, updated every release.
- Eval set, methodology, and current scores live in the repo (probably `eval/`) and are public.

Stanford pegged Lexis+ AI at 17% hallucination, Westlaw at 34%. Our target is single digits, our claim is a number, and we are honest when we miss.

### 4. Version pinning

Bills exist in multiple official versions: Introduced (IH/IS), Reported (RH/RS), Engrossed (EH/ES), Enrolled (ENR), Public Law (PL). Text often differs across versions, sometimes materially.

- Every cited span pins to one specific version.
- The system surfaces the version in the citation and lets the user query a specific version on demand.
- Cross-version diffs are a first-class feature, not an afterthought.

Most existing tools collapse versions, which is exactly the kind of detail that gets a scholar's citation challenged in peer review.

## Process commitments that follow from this

- **Ingest is a first-class system, not a one-time script.** Congress.gov + GovInfo update continuously. We track ingest lag and publish it.
- **Every public claim has a test.** "We don't hallucinate on bill numbers" needs a test in the eval set. If we cannot test it, we cannot claim it.
- **Refusal is a metric we optimize.** Too-low refusal rates mean we are confidently wrong. Too-high means the tool is unusable. We track both.
- **No marketing copy that the eval cannot back up.** If we say "0% hallucinations on sponsorship lookups," there are N tested queries showing it.
- **Provenance leaks should never be silent.** If a chunk is ever passed to the LLM without its version + URL metadata, that is a bug, not a degraded mode.

## What we are deliberately not doing

- We are not building a faster Quorum. Public-affairs/lobbying use cases want speed and breadth; we want correctness on the citations.
- We are not building a chatbot. We are building a query system that happens to accept natural language. Every output is structured (answer + spans + citations + URLs).
- We are not abstracting over state legislation in v1. US federal only. Adding 50 states is a data-quality problem we are not ready to solve.
- We are not paraphrasing legalese into plain English in v1. That is GovTrack's lane. We focus on accurate retrieval and citation; the user can read the span.

## How we know we are succeeding

A scholar can:
1. Ask a question in natural language.
2. Get an answer they can paste into a footnote.
3. Click through to the exact section of the exact bill version on Congress.gov.
4. Show their reviewer the polilabs eval score and methodology.
5. Trust that if polilabs did not know, it told them so instead of making something up.

If any of those steps fail, we have a bug to fix, not a feature to ship around.
