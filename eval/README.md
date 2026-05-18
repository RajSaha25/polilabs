# eval/

Eval harness — hand-curated query set + LLM-driven runner + structured scorer. Measures whether the agent answers correctly without hallucinating, on a fixed test set you can diff across changes.

## Files

- **`queries.yaml`** — 13 hand-curated queries across 6 categories. Each carries structured `pass_criteria` (substrings that must / must not appear, expected canonical citations, ground-truth bill sets with precision/recall scoring, abstention checks).
- **`runner.py`** — Spawns the Anthropic SDK `tool_runner` with the same 12 tools `scripts/chat.py` uses. For each query: runs the agent, captures (tool calls + arguments + responses + final answer + tokens + latency). Per-query recorder pattern because the SDK doesn't expose `tool_result` blocks in the iteration.
- **`scorer.py`** — Applies `pass_criteria` per query. Two failure modes:
  - **Under-coverage** (low recall on bill-set queries; missing required substrings; abstaining when answer is in corpus)
  - **Over-confidence** (extra bills not in ground truth; forbidden substrings present; ungrounded citations)
- **`report.py`** — Markdown report writer.
- **`last_report.md`** — Latest run's report (gitignored).

## Run it

```bash
python scripts/run_eval.py --dry-run         # verify wiring, no API call
python scripts/run_eval.py                   # full run (~$5–10 in Opus 4.7 spend)
python scripts/run_eval.py --query <id>      # single query
python scripts/run_eval.py --category out_of_scope
```

## Failure-mode design

The two failure modes the project guards against (under-coverage + over-confidence) come from the Stanford RegLab study of Lexis+ AI / Westlaw AI hallucinations. Every query scores both:

- **Set-valued queries** (e.g. "list every bill that defines AI"): precision + recall + F1 against a ground-truth bill set. Bill IDs are matched against canonical, URN, and prose forms (`H.R. 5077 ... 118th Cong.`) so the agent's prose style doesn't penalize scoring.
- **Citation grounding**: every `Sec. X(y)(z) of H.R. N` citation in the agent's answer must map to a section the agent actually fetched. Subsection drilling is allowed (citing `Sec. 2(a)(1)` after fetching `Sec. 2(a)` counts as grounded).
- **Abstention checks**: out-of-scope queries (EU AI Act, executive orders) require the agent to say so explicitly without leaking facts from training data.

## How the eval has driven design

The eval baseline went from **3/13 → 12/13** over 7 rounds, mostly by:

1. Fixing scorer bugs (the SDK doesn't expose `tool_result` blocks in iteration, so a tool-call recorder pattern was needed)
2. Adding **3 aggregate primitives** (`find_bills_defining`, `find_bills_amending`, `find_definitions_of`) — the eval exposed that agents fail systematically on "search → loop drill-in → aggregate" patterns at 20+ tool calls. Aggregates collapse those into one Cypher query.
3. Bill ID normalization (the agent calls `get_bill('H.R. 1736')`; the impl now accepts prose forms)
4. System prompt updated with explicit "prefer aggregate primitives" worked examples

Detail: each primitive added was a direct response to a documented failure. See git log for round-by-round.

## Adding a query

```yaml
- id: my_new_query
  category: definition_lookup        # or cross_bill_*, amendment_*, citation_*, out_of_scope
  question: "..."
  pass_criteria:
    answer_must_contain: ["..."]     # case-insensitive substring
    answer_must_not_contain: ["..."] # forbidden substrings
    answer_must_cite: ["Sec. X of H.R. N, ..."]  # verbatim canonical citations
    abstain: true                    # require an abstention signal
    bill_id_min: ["119-hr-1736"]     # bills that MUST appear (under-coverage check)
    bill_id_set_full: [...]          # complete ground truth (over-confidence check)
```

Run `python scripts/run_eval.py --query my_new_query` to test.

## Ground truth maintenance

For set-valued queries on a 191-bill corpus, hand-curating "every bill matching X" is intractable. Some `bill_id_set_full` values are auto-generated from the aggregate primitives (and noted as such in `queries.yaml` comments). Regenerate when the corpus changes.
