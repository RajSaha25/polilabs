"""Eval report writer: ScoredRun list → markdown.

Output is committed-friendly: deterministic order, no timestamps in the
body, suitable for cross-run diffing under git.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

from .scorer import ScoredRun


def write_report(
    scored: list[ScoredRun],
    out_path: Path,
    *,
    model: str,
    total_input_tokens: int,
    total_output_tokens: int,
    total_latency_s: float,
) -> None:
    lines: list[str] = []
    lines.append("# polilabs agent eval — run report")
    lines.append("")
    lines.append(f"- model: `{model}`")
    lines.append(f"- run at: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append(f"- total queries: {len(scored)}")
    lines.append(
        f"- total tokens: {total_input_tokens:,} input + "
        f"{total_output_tokens:,} output"
    )
    lines.append(f"- total wall time: {total_latency_s:.1f}s")
    lines.append("")

    # ----- aggregate metrics -----
    n_passed = sum(1 for s in scored if s.overall_passed)
    n_total = len(scored)
    pass_rate = n_passed / n_total if n_total else 0.0
    lines.append("## Aggregate")
    lines.append("")
    lines.append(f"- **Overall pass rate**: {n_passed}/{n_total} = {pass_rate:.0%}")

    precisions = [s.precision for s in scored if s.precision is not None]
    recalls = [s.recall for s in scored if s.recall is not None]
    f1s = [s.f1 for s in scored if s.f1 is not None]
    if precisions:
        lines.append(
            f"- **Set-valued queries** (n={len(precisions)}): "
            f"precision = {mean(precisions):.2f}, "
            f"recall = {mean(recalls):.2f}, "
            f"F1 = {mean(f1s):.2f}"
        )
        # The two failure modes Andrew named in the original brief.
        under = sum(1 for r in recalls if r < 1.0)
        over = sum(1 for p in precisions if p < 1.0)
        lines.append(
            f"  - under-coverage failures (recall<1.0): {under}/{len(recalls)}"
        )
        lines.append(
            f"  - over-confidence failures (precision<1.0): {over}/{len(precisions)}"
        )

    grounded = sum(s.grounded_citation_count for s in scored)
    ungrounded = sum(s.ungrounded_citation_count for s in scored)
    total_cites = grounded + ungrounded
    if total_cites:
        gr = grounded / total_cites
        lines.append(
            f"- **Citation grounding**: {grounded}/{total_cites} = {gr:.0%} grounded "
            f"({ungrounded} hallucinated)"
        )

    # ----- per-category breakdown -----
    by_cat: dict[str, list[ScoredRun]] = defaultdict(list)
    for s in scored:
        by_cat[s.category].append(s)
    lines.append("")
    lines.append("## By category")
    lines.append("")
    lines.append("| Category | Pass / Total | Pass % |")
    lines.append("|---|---|---|")
    for cat in sorted(by_cat):
        items = by_cat[cat]
        passed = sum(1 for s in items if s.overall_passed)
        lines.append(f"| {cat} | {passed} / {len(items)} | {passed/len(items):.0%} |")
    lines.append("")

    # ----- per-query detail -----
    lines.append("## Per-query results")
    lines.append("")
    for s in scored:
        marker = "✅" if s.overall_passed else "❌"
        lines.append(f"### {marker} `{s.query_id}` ({s.category})")
        lines.append("")
        lines.append(f"**Q**: {s.question.strip()}")
        lines.append("")
        if s.error:
            lines.append(f"**ERROR**: {s.error}")
            lines.append("")
            continue
        lines.append("**A** (truncated):")
        lines.append("")
        a = s.final_answer.strip().replace("\n", " ")
        if len(a) > 600:
            a = a[:600] + " …"
        lines.append(f"> {a}")
        lines.append("")
        lines.append("**Checks**:")
        for c in s.checks:
            mark = "✓" if c.passed else "✗"
            lines.append(f"- {mark} `{c.name}` — {c.detail}")
        if s.precision is not None:
            lines.append(
                f"- precision={s.precision:.2f}, recall={s.recall:.2f}, "
                f"F1={s.f1:.2f}"
            )
        if s.grounded_citation_count or s.ungrounded_citation_count:
            lines.append(
                f"- citations: {s.grounded_citation_count} grounded, "
                f"{s.ungrounded_citation_count} hallucinated"
            )
        lines.append("")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines))
