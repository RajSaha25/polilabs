"""Eval scorer: turn QueryRun + expected criteria into pass/fail + metrics.

Captures the two failure modes the original product brief named:

  - Under-coverage: agent gives a safe partial answer. Measured by RECALL
    on bill_id_set queries; by missing required substrings; by abstaining
    when the answer is actually in the corpus.

  - Over-confidence: agent fabricates beyond the source. Measured by
    PRECISION (extra bill IDs); by substrings the answer must NOT contain
    (e.g. specific EU AI Act articles when asked about a US bill); by
    citation grounding — every canonical citation the agent emits must
    have appeared verbatim in a tool response.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# Re-use the QueryRun type from runner without forcing a circular import.
try:
    from .runner import QueryRun
except ImportError:
    QueryRun = Any  # type: ignore[misc,assignment]


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class ScoredRun:
    query_id: str
    category: str
    question: str
    final_answer: str
    overall_passed: bool
    checks: list[CheckResult] = field(default_factory=list)
    precision: float | None = None   # for set-valued queries
    recall: float | None = None
    f1: float | None = None
    grounded_citation_count: int = 0
    ungrounded_citation_count: int = 0  # hallucinated citations
    aborted: bool = False
    error: str | None = None


# Match "Sec. X(...) of H.R. N, Cth Cong." patterns the agent emits.
_CITATION_RE = re.compile(
    r"Sec\.\s+\d+[a-zA-Z]?(?:\([^)]+\))*\s+of\s+"
    r"(?:H\.R\.|S\.|H\.J\. Res\.|S\.J\. Res\.|H\. Con\. Res\.|S\. Con\. Res\.)\s+\d+,?\s+\d+(?:st|nd|rd|th)?\s+Cong\.",
)


def _extract_citations(text: str) -> list[str]:
    return _CITATION_RE.findall(text)


def _collected_tool_text(run: QueryRun) -> str:
    """Concatenate every tool response so we can check what the agent
    actually saw vs. what it made up."""
    return " ".join(tc.response_text for tc in run.tool_calls)


def _check_must_contain(answer: str, required: list[str]) -> CheckResult:
    missing = [s for s in required if s.lower() not in answer.lower()]
    if missing:
        return CheckResult(
            "must_contain", False,
            f"missing required substrings: {missing}",
        )
    return CheckResult("must_contain", True, f"all {len(required)} present")


def _check_must_not_contain(answer: str, forbidden: list[str]) -> CheckResult:
    hits = [s for s in forbidden if s.lower() in answer.lower()]
    if hits:
        return CheckResult(
            "must_not_contain", False,
            f"forbidden substrings present (likely hallucination): {hits}",
        )
    return CheckResult("must_not_contain", True, f"all {len(forbidden)} absent")


def _check_must_cite(answer: str, required_cites: list[str]) -> CheckResult:
    # Citations are case-sensitive (canonical form) and must appear verbatim
    missing = [c for c in required_cites if c not in answer]
    if missing:
        return CheckResult(
            "must_cite", False,
            f"required canonical citations not quoted verbatim: {missing}",
        )
    return CheckResult("must_cite", True, f"all {len(required_cites)} cited")


def _check_abstain(answer: str) -> CheckResult:
    """Heuristic: a proper abstention message names the gap explicitly."""
    al = answer.lower()
    abstain_signals = [
        "not in the corpus", "not in my corpus", "outside the corpus",
        "out of scope", "out of v1 scope", "not covered",
        "i don't have", "i don't know", "cannot find",
        "i do not have", "no information",
        # Specific to the polilabs corpus_coverage message
        "regulatory", "executive order",
    ]
    if any(s in al for s in abstain_signals):
        return CheckResult("abstain", True, "abstention signal present")
    return CheckResult(
        "abstain", False,
        "no abstention signal found — likely confabulated an answer",
    )


def _check_bill_set(answer: str, full_set: list[str] | None,
                    min_set: list[str] | None) -> tuple[CheckResult, float, float]:
    """Score a set-valued answer for precision + recall against ground truth.

    Returns (CheckResult, precision, recall). full_set is the complete
    ground-truth list; min_set is the minimum subset that MUST appear.
    """
    # Normalize: bill IDs look like '119-hr-1736' or 'bill:us/119/hr/1736'.
    mentioned = set()
    # Match both forms in agent output.
    for m in re.finditer(r"\b(\d+)-([a-z]+)-(\d+)\b", answer):
        mentioned.add(f"{m.group(1)}-{m.group(2)}-{m.group(3)}")
    for m in re.finditer(r"bill:us/(\d+)/([a-z]+)/(\d+)", answer):
        mentioned.add(f"{m.group(1)}-{m.group(2)}-{m.group(3)}")

    truth = set(full_set or [])
    minreq = set(min_set or [])

    if not truth and not minreq:
        return (CheckResult("bill_set", True, "no ground truth specified"), 1.0, 1.0)

    # Recall: of the bills the agent SHOULD have named, how many did it?
    recall_base = truth or minreq
    found = mentioned & recall_base
    recall = len(found) / len(recall_base) if recall_base else 1.0

    # Precision: of the bills the agent named, how many are correct?
    # An agent that names bills outside the ground-truth set is over-confident.
    precision_base = mentioned
    if precision_base and truth:
        precision = len(precision_base & truth) / len(precision_base)
    else:
        # If we don't have a complete ground truth (only min_set), don't
        # penalize precision — the bill might be legitimately in the answer.
        precision = 1.0 if precision_base & recall_base else 0.0

    # min_set check is binary
    missing_min = minreq - mentioned
    if missing_min:
        return (CheckResult(
            "bill_set", False,
            f"under-coverage: missing required bills {sorted(missing_min)}; "
            f"precision={precision:.2f}, recall={recall:.2f}",
        ), precision, recall)

    if truth and (mentioned - truth):
        extras = sorted(mentioned - truth)
        return (CheckResult(
            "bill_set", False,
            f"over-confidence: extra bills outside ground truth {extras}; "
            f"precision={precision:.2f}, recall={recall:.2f}",
        ), precision, recall)

    return (CheckResult(
        "bill_set", True,
        f"precision={precision:.2f}, recall={recall:.2f}",
    ), precision, recall)


def _check_citation_grounding(run: QueryRun) -> tuple[int, int, CheckResult]:
    """Every Sec. X(y)(z) of H.R. N citation in the final answer must
    appear in at least one tool response (i.e., the agent quoted it from
    a get_section or get_defined_terms call, not invented it).
    """
    cites_in_answer = _extract_citations(run.final_answer)
    if not cites_in_answer:
        return (0, 0, CheckResult("citation_grounding", True, "no citations in answer"))
    tool_text = _collected_tool_text(run)
    grounded = []
    ungrounded = []
    for c in cites_in_answer:
        if c in tool_text:
            grounded.append(c)
        else:
            ungrounded.append(c)
    if ungrounded:
        return (
            len(grounded), len(ungrounded),
            CheckResult(
                "citation_grounding", False,
                f"{len(ungrounded)} unground citation(s) — "
                f"agent emitted citation(s) not in any tool response: {ungrounded[:3]}",
            ),
        )
    return (
        len(grounded), 0,
        CheckResult("citation_grounding", True,
                    f"all {len(grounded)} citations grounded in tool responses"),
    )


def score_run(run: QueryRun, query_spec: dict[str, Any]) -> ScoredRun:
    """Apply pass_criteria from queries.yaml to a QueryRun."""
    pc = query_spec.get("pass_criteria", {}) or {}
    answer = run.final_answer
    scored = ScoredRun(
        query_id=run.query_id, category=run.category, question=run.question,
        final_answer=answer, overall_passed=True,
        aborted=run.aborted, error=run.error,
    )

    if run.aborted or run.error:
        scored.overall_passed = False
        scored.checks.append(CheckResult(
            "execution", False, f"run aborted: {run.error or 'unknown reason'}",
        ))
        return scored

    if pc.get("answer_must_contain"):
        c = _check_must_contain(answer, pc["answer_must_contain"])
        scored.checks.append(c)
        scored.overall_passed = scored.overall_passed and c.passed

    if pc.get("answer_must_not_contain"):
        c = _check_must_not_contain(answer, pc["answer_must_not_contain"])
        scored.checks.append(c)
        scored.overall_passed = scored.overall_passed and c.passed

    if pc.get("answer_must_cite"):
        c = _check_must_cite(answer, pc["answer_must_cite"])
        scored.checks.append(c)
        scored.overall_passed = scored.overall_passed and c.passed

    if pc.get("abstain"):
        c = _check_abstain(answer)
        scored.checks.append(c)
        scored.overall_passed = scored.overall_passed and c.passed

    if pc.get("bill_id_min") or pc.get("bill_id_set_full"):
        c, p, r = _check_bill_set(
            answer,
            pc.get("bill_id_set_full"),
            pc.get("bill_id_min"),
        )
        scored.checks.append(c)
        scored.precision = p
        scored.recall = r
        scored.f1 = (2 * p * r / (p + r)) if (p + r) else 0.0
        scored.overall_passed = scored.overall_passed and c.passed

    # Citation grounding always runs (catches over-confidence hallucinations
    # regardless of which other checks are configured).
    grounded, ungrounded, c = _check_citation_grounding(run)
    scored.grounded_citation_count = grounded
    scored.ungrounded_citation_count = ungrounded
    scored.checks.append(c)
    if not c.passed:
        scored.overall_passed = False

    return scored


def score_all(
    runs: list[QueryRun],
    queries: list[dict[str, Any]],
) -> list[ScoredRun]:
    by_id = {q["id"]: q for q in queries}
    return [score_run(r, by_id[r.query_id]) for r in runs]
