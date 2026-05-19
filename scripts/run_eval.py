"""CLI: run the polilabs agent eval and write a markdown report.

Usage:
    python scripts/run_eval.py                       # full run, default queries
    python scripts/run_eval.py --query def_1736_ai   # single query
    python scripts/run_eval.py --dry-run             # parse + wire check, no API
    python scripts/run_eval.py --out eval/last.md

The harness requires:
  - data/polilabs.db   (SQLite, from scripts/build_index.py)
  - data/polilabs.kuzu (graph, from scripts/build_kuzu_index.py)
  - .env with ANTHROPIC_API_KEY (or --dry-run to skip API)

Cost note: a full run is ~15 queries × ~4-6 Claude Opus 4.7 tool-runner
iterations each ≈ $5-10 in API spend. --dry-run skips API entirely.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.report import write_report
from eval.runner import load_queries, run_queries
from eval.scorer import score_all


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_QUERIES = REPO_ROOT / "eval" / "queries.yaml"
DEFAULT_REPORT = REPO_ROOT / "eval" / "last_report.md"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--queries", type=Path, default=DEFAULT_QUERIES,
                    help=f"Queries YAML (default: {DEFAULT_QUERIES})")
    ap.add_argument("--out", type=Path, default=DEFAULT_REPORT,
                    help=f"Report path (default: {DEFAULT_REPORT})")
    ap.add_argument("--query", type=str, action="append", default=None,
                    help="Run only the listed query IDs (repeatable)")
    ap.add_argument("--category", type=str, action="append", default=None,
                    help="Run only the listed categories (repeatable)")
    ap.add_argument("--model", type=str, default="claude-opus-4-7")
    ap.add_argument("--dry-run", action="store_true",
                    help="Skip API calls; verify harness wiring only")
    args = ap.parse_args()

    queries = load_queries(args.queries)
    if args.query:
        queries = [q for q in queries if q["id"] in set(args.query)]
    if args.category:
        queries = [q for q in queries if q["category"] in set(args.category)]
    if not queries:
        print("error: no queries selected after filters", file=sys.stderr)
        return 2

    print(f"== polilabs eval ({len(queries)} queries, model={args.model}, "
          f"dry_run={args.dry_run}) ==")
    runs = run_queries(queries, model=args.model, dry_run=args.dry_run)
    scored = score_all(runs, queries)

    total_in = sum(r.input_tokens for r in runs)
    total_out = sum(r.output_tokens for r in runs)
    total_latency = sum(r.latency_s for r in runs)

    write_report(
        scored, args.out,
        model=args.model,
        total_input_tokens=total_in,
        total_output_tokens=total_out,
        total_latency_s=total_latency,
    )

    n_pass = sum(1 for s in scored if s.overall_passed)
    print()
    print(f"  {n_pass}/{len(scored)} passed")
    print(f"  report written to {args.out}")
    return 0 if n_pass == len(scored) else 1


if __name__ == "__main__":
    raise SystemExit(main())
