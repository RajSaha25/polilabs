"""Render the polilabs agent-eval report to LaTeX (-> PDF via pdflatex).

Reads:
  eval/results/eval_run.json   -- raw harness output (agent answers, tools)
  eval/results/grades.json     -- human-authored grade + rationale per item

Writes:
  eval/polilabs_agent_eval.tex -- compile with pdflatex

Grades are authored by review, not by the agent under test: each item's
`expected` answer was established by direct corpus queries, and every
agent answer was checked against that and the item's grading key.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_RES = _REPO / "eval" / "results"

_GRADE_COLOR = {"PASS": "passgreen", "PARTIAL": "partialorange", "FAIL": "failred"}


def _esc(s: str) -> str:
    """Escape LaTeX specials."""
    s = s or ""
    out = []
    for ch in s:
        out.append({
            "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$",
            "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}",
            "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
        }.get(ch, ch))
    return "".join(out)


def _inline(line: str) -> str:
    """Escaped line -> light markdown: **bold**, leading # headings."""
    esc = _esc(line)
    esc = re.sub(r"\*\*(.+?)\*\*", r"\\textbf{\1}", esc)
    return esc


def _block(text: str) -> str:
    """A possibly-markdown text block -> LaTeX paragraphs with line breaks."""
    paras: list[str] = []
    buf: list[str] = []
    for raw in (text or "").replace("\r", "").split("\n"):
        ln = raw.rstrip()
        stripped = ln.strip()
        # Drop pure markdown dividers / decoration-only lines.
        if stripped and set(stripped) <= set("-*=_# "):
            if buf:
                paras.append(" \\\\\n".join(buf))
                buf = []
            continue
        if not stripped:
            if buf:
                paras.append(" \\\\\n".join(buf))
                buf = []
            continue
        if stripped.startswith("#"):
            buf.append(r"\textbf{" + _inline(stripped.lstrip("# ").strip()) + "}")
        else:
            buf.append(_inline(ln))
    if buf:
        paras.append(" \\\\\n".join(buf))
    return "\n\n".join(paras) if paras else r"\textit{(no text)}"


def _tools_line(tools: list[dict]) -> str:
    if not tools:
        return r"\textit{none}"
    return ", ".join(_esc(t["name"]) for t in tools)


def _grade_badge(grade: str) -> str:
    color = _GRADE_COLOR.get(grade, "black")
    return rf"\colorbox{{{color}}}{{\textcolor{{white}}{{\bfseries {grade}}}}}"


PREAMBLE = r"""\documentclass[11pt]{article}
\usepackage[margin=1in]{geometry}
\usepackage{xcolor}
\usepackage{longtable}
\usepackage{enumitem}
\usepackage{parskip}
\usepackage{hyperref}
\usepackage{titlesec}
\definecolor{passgreen}{HTML}{1B7A3D}
\definecolor{partialorange}{HTML}{B5701A}
\definecolor{failred}{HTML}{B22222}
\definecolor{panelgray}{HTML}{F0F0EE}
\definecolor{navy}{HTML}{1F2A44}
\hypersetup{colorlinks=true,linkcolor=navy,urlcolor=navy}
\titleformat{\section}{\large\bfseries\color{navy}}{}{0pt}{}
\setlength{\parskip}{4pt}
\newcommand{\fieldlabel}[1]{\textbf{\color{navy}#1}\quad}
\begin{document}
"""


def build(run: dict, grades: dict) -> str:
    items = grades.get("items", {})
    recs = run["records"]
    # ---- scorecard tallies ----
    tally = {"PASS": 0, "PARTIAL": 0, "FAIL": 0}
    for r in recs:
        g = items.get(r["id"], {}).get("grade", "FAIL")
        tally[g] = tally.get(g, 0) + 1
    n = len(recs)

    out = [PREAMBLE]
    # ---- title ----
    out.append(r"\begin{center}")
    out.append(r"{\LARGE\bfseries\color{navy} polilabs Agent Evaluation}\\[6pt]")
    out.append(r"{\large 20-Item Quality \& Behavior Suite}\\[10pt]")
    out.append(rf"\normalsize Model: {_esc(run.get('model',''))} \quad|\quad "
               rf"Run: {_esc(run.get('started',''))} \quad|\quad "
               rf"Suite wall time: {run.get('elapsed_s','?')}\,s")
    out.append(r"\end{center}")
    out.append(r"\vspace{6pt}\hrule\vspace{10pt}")

    # ---- summary ----
    out.append(r"\section*{Summary}")
    pct = 100.0 * tally["PASS"] / n if n else 0.0
    out.append(
        rf"\noindent\fcolorbox{{navy}}{{panelgray}}{{\parbox{{0.97\textwidth}}{{"
        rf"\textbf{{Score:}} "
        rf"\textcolor{{passgreen}}{{\textbf{{{tally['PASS']} PASS}}}} \;/\; "
        rf"\textcolor{{partialorange}}{{\textbf{{{tally['PARTIAL']} PARTIAL}}}} \;/\; "
        rf"\textcolor{{failred}}{{\textbf{{{tally['FAIL']} FAIL}}}} "
        rf"\quad out of {n} items \quad({pct:.0f}\% full pass)."
        rf"}}}}")
    out.append("")
    findings = grades.get("overall_findings", "")
    if findings:
        out.append(r"\subsection*{Key findings}")
        out.append(_block(findings))

    # ---- scorecard table ----
    out.append(r"\subsection*{Scorecard}")
    out.append(r"\begin{longtable}{p{1.3cm} p{8.4cm} p{2.6cm}}")
    out.append(r"\textbf{Item} & \textbf{Category} & \textbf{Grade}\\ \hline")
    out.append(r"\endhead")
    for r in recs:
        g = items.get(r["id"], {})
        grade = g.get("grade", "FAIL")
        out.append(rf"{r['id']} & {_esc(r['category'])} & "
                   rf"{_grade_badge(grade)}\\")
    out.append(r"\end{longtable}")
    out.append(r"\newpage")

    # ---- per-item detail ----
    out.append(r"\section*{Item detail}")
    for r in recs:
        g = items.get(r["id"], {})
        grade = g.get("grade", "FAIL")
        out.append(rf"\subsection*{{{r['id']} \quad {_grade_badge(grade)}}}")
        out.append(rf"\fieldlabel{{Category.}} {_esc(r['category'])}\par")
        # question(s)
        for i, turn in enumerate(r["turns"], 1):
            lbl = f"Question (turn {i})." if len(r["turns"]) > 1 else "Question."
            out.append(rf"\fieldlabel{{{lbl}}} {_inline(turn)}\par")
        # expected
        out.append(r"\fieldlabel{Expected (corpus ground truth).}\par")
        out.append(_block(r["expected"]))
        out.append("")
        # agent answer(s) — runs x turns
        runs = r["runs"]
        for ri, run_turns in enumerate(runs, 1):
            for ti, t in enumerate(run_turns, 1):
                parts = []
                if len(runs) > 1:
                    parts.append(f"run {ri}")
                if len(run_turns) > 1:
                    parts.append(f"turn {ti}")
                suffix = (" (" + ", ".join(parts) + ")") if parts else ""
                meta = (rf"\quad{{\small\itshape "
                        rf"{t['wall_s']}s, ttft {t['ttft_s']}s, "
                        rf"tools: {_tools_line(t['tools'])}}}")
                out.append(rf"\fieldlabel{{Agent answer{suffix}.}}{meta}\par")
                if t.get("error"):
                    out.append(rf"\textcolor{{failred}}{{ERROR: "
                               rf"{_esc(t['error'])}}}\par")
                out.append(_block(t["answer"]))
                out.append("")
        # assessment
        out.append(rf"\fieldlabel{{Assessment.}} {_grade_badge(grade)}\par")
        out.append(_block(g.get("rationale", "(not graded)")))
        out.append(r"\vspace{4pt}\hrule\vspace{8pt}")

    out.append(r"\end{document}")
    return "\n".join(out)


def main() -> None:
    run = json.loads((_RES / "eval_run.json").read_text())
    grades_path = _RES / "grades.json"
    if not grades_path.exists():
        print(f"missing {grades_path} — author grades first", file=sys.stderr)
        sys.exit(1)
    grades = json.loads(grades_path.read_text())
    tex = build(run, grades)
    out_path = _REPO / "eval" / "polilabs_agent_eval.tex"
    out_path.write_text(tex)
    print(f"wrote {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
