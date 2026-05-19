# scripts/

CLI entry points. Each script is thin — it parses args and calls into a library module (`ingest/`, `index/`, `graph/`, `api/`, `eval/`).

## Build pipeline (corpus → indexes)

```bash
python scripts/smoke_test.py            # Tier 1 source reachability (Congress.gov + GovInfo + OLRC)
python scripts/fetch_candidates.py      # Phase 1.1 — GovInfo search → ranked CSV
python scripts/promote_corpus.py        # Phase 1.3 — promote candidates → data/corpus/legislation/
python scripts/build_index.py           # Phase 2.1 — build data/polilabs.db (SQLite + FTS)
python scripts/build_kuzu_index.py      # build data/polilabs.kuzu (graph spine)
```

## Verification

```bash
python scripts/api_smoke_test.py        # exercise every API primitive
python scripts/kuzu_smoke_test.py       # structural Cypher checks against the Kùzu DB
```

## Interactive use

```bash
python scripts/chat.py                  # terminal REPL (Claude Opus 4.7 + 12 tools)
python scripts/web.py                   # Gradio web UI (same agent, browser interface)
```

The MCP server lives at `mcp_server.py` (root, not `scripts/`) because it's the deployable artifact, not a dev tool.

## Eval

```bash
python scripts/run_eval.py --dry-run    # verify wiring, no API spend
python scripts/run_eval.py              # full eval (~$5–10 in Opus 4.7 spend)
python scripts/run_eval.py --query <id> # one query
```

## Adding a script

- One file per entry point. Hard-cap each script at ~100 lines of args/wiring; if you need more, the logic belongs in a library module.
- Use `argparse` with `__doc__` as the description so `--help` shows the docstring.
- Imports go through `sys.path.insert(0, str(Path(__file__).resolve().parents[1]))` (see `run_eval.py` for the pattern).
- For long-running scripts, print a one-line progress indicator per step — both `build_kuzu_index.py` and `run_eval.py` do this.
