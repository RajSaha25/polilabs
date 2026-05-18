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
        "outside the scope", "outside this corpus",
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


_BILLTYPE_PROSE = {
    "hr": [r"H\.?\s*R\.?"],
    "s": [r"S\.?"],
    "hjres": [r"H\.?\s*J\.?\s*Res\.?"],
    "sjres": [r"S\.?\s*J\.?\s*Res\.?"],
    "hconres": [r"H\.?\s*Con\.?\s*Res\.?"],
    "sconres": [r"S\.?\s*Con\.?\s*Res\.?"],
}


_VALID_CONGRESS = {"118", "119"}  # widen as corpus expands to new congresses


def _congress_after(answer: str, end: int, window: int = 60) -> str | None:
    """Find a congress marker immediately AFTER position `end`, within
    `window` chars. Forward-only because in tables ('H.R. 2385 | 119th |
    ...') the congress always trails the bill number in the same row.

    Restricts to known-valid congresses so a page count or dollar amount
    near a bill number doesn't get misread as a congress."""
    look = answer[end: end + window]
    for m in re.finditer(r"\b(\d{3})(?:st|nd|rd|th)?\b", look):
        if m.group(1) in _VALID_CONGRESS:
            return m.group(1)
    return None


# Heading-style congress context, e.g. "## 118th Congress", "**119th
# Congress (19 bills)**", "In the 118th Congress, ...". Used to attach
# congress to bills listed under that heading when the row itself omits it.
_CONGRESS_HEADING_RE = re.compile(
    r"\b(?P<num>\d{3})(?:st|nd|rd|th)\s*Cong(?:ress)?\b", re.IGNORECASE,
)


def _congress_context_at(answer: str, pos: int) -> str | None:
    """Look BACKWARD up to 2000 chars for the most recent
    `Nth Congress` heading. Returns the most recent valid one or None."""
    look = answer[max(0, pos - 2000): pos]
    matches = list(_CONGRESS_HEADING_RE.finditer(look))
    for m in reversed(matches):
        if m.group("num") in _VALID_CONGRESS:
            return m.group("num")
    return None


def _bill_id_mentioned(answer: str, bill_id: str) -> bool:
    """True iff bill_id appears in answer in any reasonable form.

    Accepts: canonical (118-hr-5077), URN (bill:us/118/hr/5077), prose
    (H.R. 5077 ... 118th Cong.). For prose forms the congress marker must
    appear within ~60 chars AFTER the bill number — forward-only, so
    table-row formats don't bleed congress markers across rows.
    """
    if bill_id in answer:
        return True
    parts = bill_id.split("-")
    if len(parts) != 3:
        return False
    congress, btype, bnum = parts
    if f"bill:us/{congress}/{btype}/{bnum}" in answer:
        return True
    proses = _BILLTYPE_PROSE.get(btype, [])
    for prose in proses:
        pat = re.compile(rf"\b{prose}\s*{bnum}\b", re.IGNORECASE)
        for m in pat.finditer(answer):
            cong = _congress_after(answer, m.end())
            if cong is None:
                # Fall back to the nearest preceding heading-style context
                # ("## 118th Congress (19 bills)" — agents group bills that
                # way in cross-congress tables).
                cong = _congress_context_at(answer, m.start())
            if cong == congress:
                return True
    return False


def _bill_set_extracted(answer: str) -> set[str]:
    """Best-effort extraction of every bill ID the agent mentioned, used
    for precision (penalizing over-confident extras). Misses prose forms
    that lack a congress marker — those go uncounted toward precision."""
    mentioned: set[str] = set()
    for m in re.finditer(r"\b(\d+)-([a-z]+)-(\d+)\b", answer):
        mentioned.add(f"{m.group(1)}-{m.group(2)}-{m.group(3)}")
    for m in re.finditer(r"bill:us/(\d+)/([a-z]+)/(\d+)", answer):
        mentioned.add(f"{m.group(1)}-{m.group(2)}-{m.group(3)}")
    for prose_btype, patterns in _BILLTYPE_PROSE.items():
        for prose in patterns:
            for m in re.finditer(
                rf"\b{prose}\s*(?P<num>\d+)\b", answer, re.IGNORECASE,
            ):
                cong = _congress_after(answer, m.end())
                if cong is None:
                    cong = _congress_context_at(answer, m.start())
                if cong:
                    mentioned.add(f"{cong}-{prose_btype}-{m.group('num')}")
    return mentioned


def _check_bill_set(answer: str, full_set: list[str] | None,
                    min_set: list[str] | None) -> tuple[CheckResult, float, float]:
    """Score a set-valued answer for precision + recall against ground truth.

    Returns (CheckResult, precision, recall). full_set is the complete
    ground-truth list; min_set is the minimum subset that MUST appear.
    """
    truth_list = full_set or []
    minreq_list = min_set or []
    # Per-bill membership check tolerates prose forms ("H.R. 5077 ... 118th Cong.").
    found_truth = {b for b in truth_list if _bill_id_mentioned(answer, b)}
    found_min = {b for b in minreq_list if _bill_id_mentioned(answer, b)}
    # Aggregate set for precision math (treats truth + min as recall base).
    mentioned = _bill_set_extracted(answer)

    truth = set(truth_list)
    minreq = set(minreq_list)

    if not truth and not minreq:
        return (CheckResult("bill_set", True, "no ground truth specified"), 1.0, 1.0)

    # Recall: of the bills the agent SHOULD have named, how many did it?
    # Uses per-bill membership check so prose ("H.R. 5077") counts.
    recall_base = truth or minreq
    found_recall = found_truth if truth else found_min
    recall = len(found_recall) / len(recall_base) if recall_base else 1.0

    # Precision: of the bills the agent named, how many are correct?
    # An agent that names bills outside the ground-truth set is over-confident.
    precision_base = mentioned
    if precision_base and truth:
        precision = len(precision_base & truth) / len(precision_base)
    else:
        precision = 1.0 if precision_base & recall_base else 0.0

    # min_set check is binary — use per-bill (prose-tolerant) detection.
    missing_min = minreq - found_min
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


_CITATION_DECOMPOSE_RE = re.compile(
    r"(?P<head>Sec\.\s+\d+[a-zA-Z]?)(?P<subs>(?:\([^)]+\))*)"
    r"(?P<tail>\s+of\s+(?:H\.R\.|S\.|H\.J\. Res\.|S\.J\. Res\.|H\. Con\. Res\.|S\. Con\. Res\.)\s+\d+,?\s+\d+(?:st|nd|rd|th)?\s+Cong\.)",
)


def _citation_section_root(citation: str) -> str:
    """Strip subsection enums from a citation, leaving the section-level
    anchor. 'Sec. 2(a)(1) of H.R. 7913, 118th Cong.' → 'Sec. 2 of H.R.
    7913, 118th Cong.'. Used for grounding: subsection drilling within a
    section returned by get_section is legitimate, not hallucination."""
    m = _CITATION_DECOMPOSE_RE.match(citation)
    if not m:
        return citation
    return m.group("head") + m.group("tail")


def _check_citation_grounding(run: QueryRun) -> tuple[int, int, CheckResult]:
    """Every Sec. X(y)(z) of H.R. N citation in the final answer must
    map to a section the agent actually fetched. We match at section
    level (subsection enums stripped): once the agent has the verbatim
    text of Sec. 2(a) it can correctly cite Sec. 2(a)(1) inside it.
    """
    cites_in_answer = _extract_citations(run.final_answer)
    if not cites_in_answer:
        return (0, 0, CheckResult("citation_grounding", True, "no citations in answer"))
    tool_text = _collected_tool_text(run)
    grounded = []
    ungrounded = []
    for c in cites_in_answer:
        if c in tool_text or _citation_section_root(c) in tool_text:
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
