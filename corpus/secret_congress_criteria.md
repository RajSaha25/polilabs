# Secret-congress / electoral-consequence corpus — inclusion criteria (v1)

Source of truth for what counts as a `secret_congress` item. The seed
fetcher (`scripts/fetch_secret_congress_seed.py`) references this file; do
not change criteria informally.

## What this corpus is about

The AI-governance and redistricting corpora are organized by *subject
matter*. This corpus is organized by *passage dynamics*: how bills become
law (or fail) as a function of bipartisanship, media salience, and
electoral pressure. The name comes from the "secret congress" thesis
(Yglesias/Bazelon, Slow Boring, 2021): major legislation passes on broad
bipartisan votes precisely when it stays out of the partisan media
spotlight, while high-salience bills collapse into messaging exercises.

The corpus exists to let an agent answer questions like:

- Which major laws passed with large minority-party support, and on which
  votes? (CHIPS, water infrastructure, PACT Act, postal reform)
- Which bipartisan bills *failed*, and what does the record say about
  why? (Border Act 2024 — failed cloture after presidential-campaign
  pressure; KOSA — passed Senate 91-3 and was never brought up in the
  House; DISCLOSE — failed cloture 49-49 on party lines)
- Which laws were enacted inside a single omnibus vehicle rather than
  standalone? (Electoral Count Reform Act inside the FY2023 omnibus)
- What does a party-line enactment look like by contrast? (IRA, OBBBA)

## Inclusion rule (v1)

Hand-curated, like the redistricting seed. A bill qualifies if it is a
**named, nationally reported federal bill of the 117th–119th Congress**
that is a clear exemplar of at least one cluster below. Every entry must
be verified against its BILLSTATUS record (title match) before promotion;
bill numbers are never trusted from memory.

## Clusters

Each bill carries exactly one `cluster` tag in metadata.json:

| Cluster | Definition |
|---|---|
| `quiet_bipartisan_law` | Enacted with large minority-party support and comparatively low national media salience (the secret-congress core case). |
| `high_salience_bipartisan_law` | Enacted with meaningful cross-party support despite high salience. |
| `bipartisan_but_died` | Substantial cross-party support on the record, but never enacted (failed cloture, failed passage, or never scheduled). |
| `absorbed_into_vehicle` | Died as a standalone bill but its substance was enacted inside another bill in the corpus. |
| `omnibus_vehicle` | A vehicle bill that carried multiple unrelated measures to enactment in a single vote. |
| `party_line_contrast` | Enacted or passed one chamber on a party-line vote — the contrast class for the bipartisan clusters. |

Cluster assignments are curatorial. The *vote record* (party splits,
`bipartisan_support`) is mechanical and lives in `billstatus.json`; an
agent that distrusts the cluster tag can recompute from the votes.

## Date range

117th Congress (2021-01-03) through present. The 117th is in scope —
unlike the AI corpus — because the canonical secret-congress exemplars
(CHIPS, IIJA, PACT, postal reform, ECRA) are 117th-Congress laws.

## Deliberate exclusions

- **Freedom to Vote Act / John R. Lewis VRAA** (117-hr-5746, 117-s-2747,
  HR 1/S 1, etc.): already in the `redistricting` corpus. `bill_id` is a
  primary key across topics, so a bill lives in exactly one topic; the
  redistricting copies carry the relevant vote history.
- Appropriations bills other than 117-hr-2617 (one omnibus exemplar is
  enough for v1).
- Annual NDAAs other than 117-hr-7776 (included only because it is the
  WRDA-2022-turned-NDAA vehicle).

## What this file controls

- The seed list in `scripts/fetch_secret_congress_seed.py`
- The `cluster` vocabulary in metadata.json for topic `secret_congress`
- The corpus_coverage() description of this topic
