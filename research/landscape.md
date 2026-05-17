# Landscape: Existing tools for queryable legislative data

Snapshot as of 2026-05-17. Focus is US federal bills/legislation, scholar use case, citation accuracy.

## TL;DR — who is closest to what we want to build

Nobody is doing exactly what polilabs aims to do (scholar-first, citation-accurate, conversational interface over US federal legislation with span-level provenance). The closest analogs split along three axes:

1. **Authoritative + free, no AI**: Congress.gov + GovInfo bulk XML. Gold standard for citation, manual to navigate.
2. **AI + commercial, lobbyist-priced**: Quorum's AI Bill Tracking and FiscalNote PolicyNote. Semantic search and summaries, but target public-affairs buyers and have known hallucination issues.
3. **Academic dataset, structured, no LLM**: Congressional Bills Project (Adler & Wilkerson). Topic-coded bills but data largely stops in the mid-2010s.

The strongest gap to attack: a free or low-cost, scholar-facing tool that combines (a) Congress.gov-grade citation accuracy with (b) natural-language querying and (c) the hallucination-mitigation approach validated by the Stanford RegLab study (forced retrieval, span-level provenance, refuse-if-uncertain).

---

## 1. Authoritative data sources (where bills actually live)

### Congress.gov API (api.congress.gov)
- Official Library of Congress API, free with API key.
- Covers bills 1973-present, full text 1993-present, member profiles, treaties, committee reports.
- The recommended replacement for everything else (ProPublica, GovTrack are deprecating in favor of this).
- **Use for polilabs**: primary metadata + status pull.

### GovInfo bulk XML (govinfo.gov/bulkdata/BILLS)
- GPO + Library of Congress. Public-domain bulk download of full bill text in USLM XML.
- Three companion collections: BILLS (full text), BILLSTATUS (sponsorship + history), BILLSUM (official short summaries).
- Bill status XML now covers 108th-119th Congress (2003-present) after a 2020 release expanded historical coverage.
- **Use for polilabs**: ingest backbone. Full XML lets us preserve section/paragraph IDs as stable citation anchors.

### @unitedstates/congress (github.com/unitedstates/congress)
- Public-domain scraper originally by GovTrack + Sunlight Foundation, now maintained by GovTrack and others.
- Wraps Congress.gov + GovInfo into normalized JSON; mature, widely depended on.
- **Use for polilabs**: shortcut for the ingest pipeline if we don't want to write XML parsers ourselves.

### Deprecating but worth noting
- **ProPublica Congress API**: no longer issuing new keys, sunsetting; recommends Congress.gov API.
- **GovTrack open data + API**: terminating summer 2026, redirecting to Congress.gov or @unitedstates scrapers.

The whole independent-data-mirror ecosystem is consolidating onto the official Congress.gov + GovInfo stack. That is good for us (one source of truth) and means we should design around those endpoints.

---

## 2. Open academic datasets

### Congressional Bills Project (congressionalbills.org)
- ~400,000 bills from the 80th-110th Congress (1947 onward, last update ~2008-2015 depending on source).
- Manually classified using the Policy Agendas Project topic schema (one major topic + subtopic per bill). This is rare and valuable for political science.
- Run out of UT Austin / U Washington (Adler & Wilkerson).
- Widely cited in legislative-behavior research.
- **Use for polilabs**: borrow the topic taxonomy. The dataset itself is stale; we would refresh it.

### "A Century of Lawmaking" (Library of Congress)
- Searchable text of the Congressional Record + precursors, 1774-1875.
- Not useful for modern bills but relevant if scholars want historical reach.

### ProQuest Congressional / Legislative Insight
- The dominant paid scholarly database (committee prints, CRS reports, hearings, Public Laws 1789-present).
- Library subscription, not API-friendly, not AI-queryable.
- This is what scholars currently *cite* from. Worth understanding the citation format they produce.

---

## 3. Commercial AI-powered platforms

These are the closest competitors on the AI/query dimension. All are priced for lobbyists, public-affairs teams, and government-relations professionals (typically $10K-$100K+/year). None target scholars.

### Quorum (quorum.us)
- In-house data team for federal + state + local + EU.
- "AI Bill Tracking" feature (rolled out to all Quorum customers): AI bill summaries + semantic search.
- AI-powered speaker identification on committee transcripts.
- Markets itself as more reliable than FiscalNote because of unified in-house data.
- **Closest competitor on the AI-over-Congress dimension.**

### FiscalNote / PolicyNote
- Earliest entrant in AI policy intelligence (founded 2013).
- Data sourced from multiple acquisitions; criticized for lag and inconsistencies across components.
- Has AI summaries and analysis features.
- Targets enterprise government-relations buyers.

### Plural Policy (formerly OpenStates Pro)
- Spun out of Open States; positions itself against FastDemocracy and Quorum.
- Strong on state-level tracking.

### BillTrack50
- Free AI-generated bill summaries for nonprofits.
- Targets associations and small advocacy orgs.
- The "free AI bill summary" lane is already taken here, but it is summary-only and not query/citation-focused.

### Bloomberg Government
- Heavyweight subscription product for legal/financial buyers. Strong on regulatory tracking, less AI-forward in 2026.

---

## 4. Free / nonprofit AI-on-Congress projects

### POPVOX Foundation (popvox.org)
- Nonprofit focused on legislative-branch AI use cases.
- Built **StaffLink** (stafflinkbot.org), a RAG bot trained on public Congressional staff onboarding materials.
- Publishes report "Representative Bodies in the AI Era: GenAI in the US Congress and State Legislatures."
- Working with Brazil's Senate on a RAG tool for procedural rules (Constitution + Rulebook).
- **Most ideologically aligned with polilabs**: nonprofit, RAG-first, citation-conscious, legislative-branch focused. But their tools target Congressional *staff*, not external scholars, and StaffLink is over onboarding docs, not bill text.

### GovTrack.us
- Free public tool, plain-language bill explanations, but no LLM interface. API sunsetting.

### The Congress Project (thecongressproject.com)
- Aggregation/links site, organizing Congressional data sources. Useful as a meta-resource.

---

## 5. The hallucination problem (the polilabs thesis, validated)

The Stanford RegLab + HAI study "Hallucination-Free? Assessing the Reliability of Leading AI Legal Research Tools" (Magesh, Surani, Dahl, Suzgun, Manning, Ho — preprint May 2024, peer-reviewed in J. Empirical Legal Studies 2025) found:

- Lexis+ AI hallucinates **17%** of the time, accurate 65%.
- Westlaw AI-Assisted Research hallucinates **34%** of the time, accurate 42%.
- GPT-4 baseline hallucinates 43%.
- Methodology: ~200 manually constructed pre-registered open-ended legal queries.

Key takeaway: **commercial RAG-protected legal tools still hallucinate at substantial rates.** The promise of "RAG = no hallucinations" does not hold in practice without aggressive design choices (forced citation anchors, refusal under uncertainty, span-level retrieval, eval-driven iteration).

This is the empirical foundation of polilabs' value proposition. We have to do better than 17% on the specific task of "cite this bill text correctly," not just claim we will.

Parallel signal: throughout 2025-2026 there have been multiple high-profile attorney sanctions for filing briefs with AI-hallucinated case citations (multistate.ai / compliancehub.wiki tracking). The market is aware of the problem; users do not yet have a trusted answer.

---

## 6. Gap analysis — where polilabs can stand out

| Dimension | State of the field | Polilabs opportunity |
|---|---|---|
| Audience | Lobbyists (Quorum, FiscalNote) or staff (POPVOX) | **Scholars** — political scientists, historians, legal researchers, journalists |
| Pricing | Enterprise ($$$$) or free-but-shallow (BillTrack50) | Free or low-cost, with citation guarantees |
| Data freshness | Academic datasets stop ~2015; commercial tools are current | Pull from Congress.gov + GovInfo directly, current |
| Citation format | Either copy-paste from Congress.gov (manual) or summary text with weak provenance (commercial AI) | Span-level, copy-paste-ready citations (Bluebook + APA + Chicago) tied to stable bill IDs |
| Hallucination control | 17-34% on commercial legal AI (Stanford) | Eval-first design, refuse under uncertainty, every claim backed by a retrieved span |
| Topic coding | Congressional Bills Project (stale, 1947-2015) | Refresh the Policy Agendas taxonomy with an LLM + human review loop |
| API access | Available from Congress.gov but raw; commercial APIs locked behind sales | Open API for researchers + reproducible query logs |

The most defensible bundle: **a scholar-facing query interface that returns answers + Bluebook-formatted citations + the exact bill text span the answer rests on, with a verifiable URL into Congress.gov and a stable bill-version ID. Plus a public eval suite that measures hallucination rate the way Stanford did, so we can claim numbers honestly.**

---

## 7. Open questions for next iteration of research

1. What is the actual citation format scholars use for federal bills? (Bluebook is the legal standard; political science varies.) Need to specify the output format precisely.
2. Does any tool already do span-level provenance well for legislation? (Westlaw's AI does case-law spans; not sure about bills specifically.) Worth one more deep dive.
3. How are scholars currently using LLMs for bill research, and what are their pain points? (Survey? Interview? Look for existing studies.)
4. What is the right scope of "legislation" for v1? Just bills, or also: committee reports, CRS reports, the Congressional Record, Public Laws, signing statements? ProQuest Congressional bundles all of these.
5. Is there a regulatory-text analog we should also handle? (Federal Register / regulations.gov.) Probably out of scope for v1.

---

## Sources

- [Congress.gov API](https://api.congress.gov/)
- [GovInfo bulk data BILLS](https://www.govinfo.gov/bulkdata/BILLS)
- [GPO + LoC 10-year bulk data release](https://www.gpo.gov/who-we-are/news-media/news-and-press-releases/gpo-and-library-of-congress-release-ten-years-of-legislative-data-on-govinfo)
- [@unitedstates/congress scraper](https://github.com/unitedstates/congress)
- [Congressional Bills Project](http://www.congressionalbills.org/)
- [Ending GovTrack's bulk data and API](https://congressionaldata.org/ending-govtracks-bulk-data-and-api/)
- [ProPublica Congress API (deprecating)](https://projects.propublica.org/api-docs/congress-api/)
- [Quorum AI Bill Tracking](https://www.quorum.us/blog/ai-bill-tracking-advanced-legislative-intelligence/)
- [FiscalNote vs Quorum comparison](https://fiscalnote.com/blog/fiscalnote-vs-quorum)
- [BillTrack50 AI summaries for nonprofits](https://www.nonprofitpro.com/article/billtrack50-boosts-nonprofits-access-to-state-legislation-with-ai-generated-bill-summaries/)
- [POPVOX Foundation: What Is RAG for Legislative AI](https://www.popvox.org/blog/what-is-rag-and-why-it-matters-for-legislative-ai-use-cases)
- [POPVOX AI for the Legislative Branch](https://www.popvox.org/artificial-intelligence)
- [Stanford RegLab: Hallucination-Free? Legal RAG study](https://reglab.stanford.edu/publications/hallucination-free-assessing-the-reliability-of-leading-ai-legal-research-tools/)
- [Stanford HAI summary of legal AI hallucinations](https://hai.stanford.edu/news/ai-trial-legal-models-hallucinate-1-out-6-or-more-benchmarking-queries)
- [Stanford full PDF: Legal RAG Hallucinations](https://dho.stanford.edu/wp-content/uploads/Legal_RAG_Hallucinations.pdf)
- [LegiScan API](https://legiscan.com/legiscan)
- [Library of Congress legislative resources guide](https://guides.loc.gov/law-library-of-congress-databases/legislative-and-statutory-resources)
- [Georgetown Law: Legislative History Research Guide](https://guides.ll.georgetown.edu/legislative_history)
