# polilabs

Queryable, citation-accurate database of US federal legislation for scholars.

The v1 wedge corpus is **AI-governance** legislation: federal bills since ~2017 that touch AI, machine learning, algorithmic decision-making, or related policy. The architecture is built to generalize to any domain.

## Tier 1 data sources (this commit)

| Source | Role | Auth | Cost |
|---|---|---|---|
| **Congress.gov API** | Bill metadata, sponsors, votes, actions | API key | Free |
| **GovInfo API** | Full text of bills, public laws, US Code | API key | Free |
| **OLRC bulk XML** | US Code as point-in-time release points | None | Free |

Together these are the public-domain spine. A future Tier 2 layer (Lexis / Bloomberg / Westlaw citator APIs) is intentionally deferred — see project notes.

## Setup

### 1. Get API keys (instant)

- **Congress.gov**: sign up at <https://api.congress.gov/sign-up/>. Key arrives by email in seconds. Rate limit: 5,000 req/hr.
- **GovInfo**: sign up at <https://api.govinfo.gov/docs> (the "Get API Key" link goes to api.data.gov). Key shown immediately and emailed.

OLRC needs no key — it's just static ZIP downloads of US Code release points.

### 2. Drop keys into `.env`

```bash
cp .env.example .env
# then edit .env and paste in the two keys
```

### 3. Install and smoke-test

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .
python scripts/smoke_test.py
```

You should see one bill from the 118th Congress, six GovInfo collection codes, and an HTTP 200 from the OLRC release-points index.

## Layout

```
sources/
  congress_gov.py   # Library of Congress API client
  govinfo.py        # GPO GovInfo API client
  olrc.py           # OLRC US Code bulk-XML download helpers
scripts/
  smoke_test.py     # Verifies all three sources are reachable
research/
  landscape.md      # Prior research on the data-source landscape
```

## Design notes

- **Cross-check, don't wrap.** The product value comes from the reconciliation layer across sources — not from being a wrapper on any single API. Each client here is intentionally thin.
- **AI-native is what we build, not what we consume.** Raw GovInfo XML is authoritative but not agent-queryable; making it queryable is the project.
- **Versioned law matters.** Scholars need "what did the law say on date X." That's why OLRC release points are in Tier 1, not the live Congress.gov bill text alone.
