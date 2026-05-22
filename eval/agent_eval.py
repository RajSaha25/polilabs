"""polilabs agent evaluation harness.

Runs a fixed 20-item question suite through the /chat agent in-process,
capturing each answer, the tools the agent called, and per-turn latency.
Writes eval/results/eval_run.json for grading + the PDF report.

Each item carries an `expected` answer and a `grading_key`. Those were
established by direct, deterministic corpus queries (data/polilabs.db
plus the mechanical api/_impl.py extractors) — independent of the agent
under test. The suite deliberately covers normal retrieval, session
memory (multi-turn), out-of-corpus prompts, a repeated question
(consistency), and a false-premise prompt (hallucination probe).

Usage (from the repo root):
    POLILABS_DB=$PWD/data/polilabs.db POLILABS_KUZU=$PWD/data/polilabs.kuzu \
        python eval/agent_eval.py
"""
from __future__ import annotations

import concurrent.futures
import json
import sys
import time
from pathlib import Path

# A healthy turn is seconds to ~40s; this only catches a true hang so one
# bad turn cannot stall the whole suite.
TURN_TIMEOUT_S = 240

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

import server  # noqa: E402


# --- the 20-item suite -------------------------------------------------
# turns: list of user messages (>1 == multi-turn, history is replayed).
# repeat: number of independent fresh sessions (Q18 == consistency probe).

ITEMS: list[dict] = [
    {
        "id": "Q1", "category": "corpus scope",
        "turns": ["How many bills are in this corpus, and which Congresses "
                  "and time span do they cover?"],
        "expected": "191 bills, covering the 118th Congress (100 bills) and "
                    "119th Congress (91 bills); introduction dates span "
                    "January 9, 2023 to May 4, 2026.",
        "grading_key": ["191 total bills", "118th + 119th Congress (100 / 91)",
                        "span ~2023-01 to 2026-05"],
    },
    {
        "id": "Q2", "category": "single-bill fact",
        "turns": ["Who sponsored the AI Fraud Deterrence Act, and when was "
                  "it introduced?"],
        "expected": "The AI Fraud Deterrence Act (H.R. 10125, 118th Congress) "
                    "was sponsored by Rep. Ted Lieu (D-CA-36) and introduced "
                    "on November 14, 2024.",
        "grading_key": ["sponsor Rep. Ted Lieu (D-CA)", "introduced 2024-11-14"],
    },
    {
        "id": "Q3", "category": "single-bill substantive",
        "turns": ["What does the AI Labeling Act of 2023 require, and who "
                  "must comply with it?"],
        "expected": "Exists as House (H.R. 6466) and Senate (S. 2691) "
                    "companion bills, identical text. Requires generative AI "
                    "systems to attach clear, conspicuous, permanent "
                    "disclosures that content is AI-generated (metadata for "
                    "image/video/audio, notice for text/chatbots). Developers "
                    "and third-party licensees must prevent downstream removal "
                    "of disclosures. FTC enforces as an unfair/deceptive act.",
        "grading_key": ["identifies H.R. 6466 / S. 2691 companions",
                        "disclosure/labeling of AI-generated content",
                        "developers AND licensees prevent removal",
                        "FTC enforcement"],
    },
    {
        "id": "Q4", "category": "conceptual retrieval",
        "turns": ["Which bills in the corpus address AI-generated deepfakes?"],
        "expected": "~10 bills mention deepfakes, including the No AI FRAUD "
                    "Act (118-hr-6943), Protecting Consumers from Deceptive AI "
                    "Act (118-hr-7766 / 119-hr-8479), AI PLAN Act, AI Public "
                    "Awareness and Education Campaign Act, American Leadership "
                    "in AI Act, and the AI Scam Prevention Act. Several are "
                    "companion/reintroduced pairs.",
        "grading_key": ["defensible set of ~6-10 bills",
                        "names No AI FRAUD Act + Protecting Consumers from "
                        "Deceptive AI Act", "notes companion/reintro pairs"],
    },
    {
        "id": "Q5", "category": "conceptual retrieval (vocabulary gap)",
        "turns": ["Which bills restrict exports of advanced AI chips or "
                  "semiconductors to foreign adversaries?"],
        "expected": "H.R. 4683 (CLOUD AI Act — blocks cloud/remote access to "
                    "advanced ICs for China/Macau entities) and H.R. 5885 "
                    "(GAIN AI Act — advanced-IC export license requirement). "
                    "S. 321 (Decoupling America's AI Capabilities from China "
                    "Act) bars import/export of AI tech/IP. H.R. 6996 'Full AI "
                    "Stack Export Promotion Act' is the opposite — it promotes "
                    "exports — and must not be miscounted.",
        "grading_key": ["H.R. 4683 / CLOUD AI Act restricts advanced-IC access",
                        "names GAIN AI Act (119-hr-5885) and/or 119-s-321",
                        "does NOT miscount H.R. 6996 (export promotion)"],
    },
    {
        "id": "Q6", "category": "aggregate count",
        "turns": ["How many bills in the corpus were introduced in the "
                  "119th Congress?"],
        "expected": "91 bills were introduced in the 119th Congress.",
        "grading_key": ["exact count 91"],
    },
    {
        "id": "Q7", "category": "aggregate fact",
        "turns": ["Which member of Congress sponsored the most bills in this "
                  "corpus, and how many?"],
        "expected": "Rep. Ted Lieu (D-CA-36) sponsored the most, with 10 bills.",
        "grading_key": ["Rep. Ted Lieu", "10 bills"],
    },
    {
        "id": "Q8", "category": "definitions aggregate",
        "turns": ["How do bills in the corpus define \"artificial "
                  "intelligence\"? Are the definitions consistent across bills?"],
        "expected": "57 bills define 'artificial intelligence'. They are "
                    "largely consistent: 42 define it by reference, and 35 of "
                    "those point to 15 U.S.C. 9401 (the National AI Initiative "
                    "Act of 2020 definition). Only 15 write a direct "
                    "definition, and those track the same structure. The "
                    "corpus converges on the 15 U.S.C. 9401 statutory "
                    "definition.",
        "grading_key": ["~57 bills define the term",
                        "majority define by reference, mostly 15 U.S.C. 9401",
                        "definitions broadly consistent"],
    },
    {
        "id": "Q9", "category": "amendment graph",
        "turns": ["Which bills in the corpus amend the Communications Act "
                  "of 1934?"],
        "expected": "H.R. 8939 and H.R. 334 (companion bills amending "
                    "§227(d)(3) for AI-generated voice), S. 1993 (amends §230 "
                    "to waive interactive-computer-service immunity for "
                    "generative-AI claims), H.R. 7786 (AI Fraud Accountability "
                    "Act, §223), and S. 3495 (AI Scam Prevention Act, §§227 & "
                    "230). Bills that merely mention the Act are not amenders.",
        "grading_key": ["confirms 119-hr-334, 118-hr-8939, 118-s-1993 amend it",
                        "H.R. 8939/334 = §227 voice; S. 1993 = §230",
                        "distinguishes amenders from mere mentions"],
    },
    {
        "id": "Q10", "category": "definitions (honest-null probe)",
        "turns": ["Which bills in the corpus, if any, define the term "
                  "\"frontier model\"?"],
        "expected": "No bill in the corpus defines 'frontier model'. The "
                    "definition index and full-text search both return zero "
                    "matches. (S. 5616 uses the distinct term 'covered "
                    "frontier artificial intelligence model'.)",
        "grading_key": ["answer is none / zero bills",
                        "does not fabricate a definition"],
    },
    {
        "id": "Q11", "category": "single-bill substantive",
        "turns": ["What does the Generative AI Terrorism Risk Assessment Act "
                  "require?"],
        "expected": "H.R. 1736 (119th Congress) requires DHS, with the DNI, "
                    "to deliver an annual assessment to Congress for five "
                    "years of terrorism threats from terrorist use of "
                    "generative AI. It also directs DHS to review/disseminate "
                    "fusion-center intelligence and obliges agencies to share "
                    "information with DHS. It is a reporting mandate, not an "
                    "AI restriction.",
        "grading_key": ["DHS (with DNI) recurring ~5-yr assessments to Congress",
                        "fusion centers / interagency info sharing",
                        "a reporting mandate, not an AI restriction"],
    },
    {
        "id": "Q12", "category": "long comparison",
        "turns": ["Compare the AI disclosure obligations in the AI Labeling "
                  "Act versus the Generative AI Copyright Disclosure Act of "
                  "2024. What does each require, and who is the target of "
                  "each?"],
        "expected": "The AI Labeling Act requires outward, consumer-facing "
                    "labeling — generative AI systems must mark output as "
                    "AI-generated, developers/licensees enforce non-removal, "
                    "FTC oversight. The Generative AI Copyright Disclosure Act "
                    "of 2024 (H.R. 7913) requires upstream, regulator-facing "
                    "disclosure — whoever builds or significantly alters an AI "
                    "training dataset must file a notice with the Copyright "
                    "Office summarizing copyrighted works used, ≥30 days "
                    "before public release.",
        "grading_key": ["AI Labeling Act = consumer-facing labeling of output",
                        "H.R. 7913 = filing with Register of Copyrights about "
                        "training-data copyrighted works",
                        "contrasts the targets/audiences correctly"],
    },
    {
        "id": "Q13", "category": "session memory (multi-turn)",
        "turns": ["What is the AI for National Security Act?",
                  "Who introduced it, and which Congress was it in?"],
        "expected": "Turn 1: H.R. 1718 amends the NDAA FY2022 to modify DoD "
                    "enterprise-wide cyber-data procurement, providing for "
                    "AI-based endpoint security without constant internet "
                    "connectivity. Turn 2 (memory): must resolve 'it' to that "
                    "same bill — sponsor Rep. Jay Obernolte (R-CA), 118th "
                    "Congress (introduced March 22, 2023).",
        "grading_key": ["turn 1 identifies H.R. 1718 / DoD cyber procurement",
                        "turn 2 resolves 'it' to the same bill (no re-ask)",
                        "turn 2: Rep. Jay Obernolte, 118th Congress"],
    },
    {
        "id": "Q14", "category": "session memory (multi-turn)",
        "turns": ["Which bills in the corpus mention facial recognition?",
                  "Summarize the first one for me."],
        "expected": "Turn 1: three bills — ASSESS AI Act (S. 1356, 118th), AI "
                    "Foundation Model Transparency Act of 2023 (H.R. 6881, "
                    "118th), LIFE with AI Act (S. 3063, 119th). Turn 2 "
                    "(memory): must summarize one of those three (ideally "
                    "S. 1356, earliest) without re-running the search from "
                    "scratch or drifting to an unrelated bill.",
        "grading_key": ["turn 1 lists the 3 facial-recognition bills",
                        "turn 2 summarizes one of those same 3 bills",
                        "turn 2 stays anchored to turn 1's result set"],
    },
    {
        "id": "Q15", "category": "out-of-corpus (state law)",
        "turns": ["What does the California AI Transparency Act require?"],
        "expected": "Out of scope. The corpus is U.S. federal legislation "
                    "only; the California AI Transparency Act (SB 942) is a "
                    "California state statute and is not in the corpus. The "
                    "agent should decline to answer from the corpus rather "
                    "than fabricate provisions.",
        "grading_key": ["recognizes it as California state law, not federal",
                        "states it is not in the corpus",
                        "does not invent requirements"],
    },
    {
        "id": "Q16", "category": "out-of-corpus (foreign law)",
        "turns": ["Summarize the EU AI Act's risk tiers."],
        "expected": "Out of scope. The corpus holds only U.S. federal "
                    "legislation; the EU AI Act is European Union law. The "
                    "agent should flag it as out of scope rather than recite "
                    "the risk tiers as if corpus-grounded.",
        "grading_key": ["identifies the EU AI Act as foreign / EU law",
                        "states it is not in the corpus / out of scope",
                        "does not present a corpus-grounded answer"],
    },
    {
        "id": "Q17", "category": "out-of-corpus (nonexistent bill)",
        "turns": ["What does H.R. 9999 from the 119th Congress say about AI?"],
        "expected": "There is no bill 119-hr-9999 in the corpus (the highest "
                    "119th-Congress H.R. number present is 8664). The agent "
                    "should say it is not in the corpus and not fabricate "
                    "content.",
        "grading_key": ["states 119-hr-9999 is not in the corpus",
                        "does not invent bill content"],
    },
    {
        "id": "Q18", "category": "consistency (repeated question)",
        "turns": ["How many bills in the corpus were introduced in the "
                  "118th Congress?"],
        "repeat": 4,
        "expected": "100 bills were introduced in the 118th Congress — and "
                    "the answer must be identical across all 4 independent "
                    "askings.",
        "grading_key": ["exact count 100", "identical across all 4 runs"],
    },
    {
        "id": "Q19", "category": "long analytical",
        "turns": ["Across the whole corpus, what are the main regulatory "
                  "approaches to AI — for example disclosure, liability, "
                  "government use, research funding — and roughly how "
                  "prevalent is each approach?"],
        "expected": "The corpus leans toward soft-touch / government-facing "
                    "measures: study and task-force mandates and research "
                    "funding are the most common, followed by AI "
                    "education/workforce and standards/NIST frameworks. "
                    "Government use/procurement and national-security "
                    "provisions are common. Hard regulatory levers — "
                    "disclosure/transparency and liability — appear in a "
                    "minority (~1/3 each); export controls and "
                    "deepfake-specific measures are narrower still. Prevalence "
                    "is approximate and overlapping.",
        "grading_key": ["names disclosure, liability, government use, research "
                        "funding, standards as the main approaches",
                        "conveys studies/research/standards most prevalent, "
                        "hard regulation less so",
                        "acknowledges the breakdown is approximate"],
    },
    {
        "id": "Q20", "category": "false premise (hallucination probe)",
        "turns": ["The corpus contains the AI Safety Act of 2022 — summarize "
                  "its key provisions."],
        "expected": "False premise. No bill titled 'AI Safety Act of 2022' "
                    "exists, and the corpus contains no 2022 legislation at "
                    "all (it starts with the 118th Congress; earliest bill "
                    "January 9, 2023). The agent should reject the premise, "
                    "not summarize fabricated provisions.",
        "grading_key": ["rejects the premise — no such bill exists",
                        "notes the corpus starts in 2023 / 118th Congress",
                        "does not fabricate provisions"],
    },
]


# --- runner ------------------------------------------------------------


def _run_turn(message: str, history: list[dict]) -> dict:
    """Drive one /chat turn in-process; collect answer, tools, timing."""
    req = server.ChatRequest(
        message=message,
        history=[server.ChatMessageIn(**h) for h in history],
    )
    t0 = time.perf_counter()
    answer_parts: list[str] = []
    tools: list[dict] = []
    n_tool_results = 0
    ttft = None
    error = None
    for raw in server._stream_chat(req):
        payload = json.loads(raw[len("data: "):])
        et = payload.get("type")
        if et == "text":
            if ttft is None:
                ttft = time.perf_counter() - t0
            answer_parts.append(payload["delta"])
        elif et == "tool_call":
            tools.append({"name": payload["name"], "args": payload.get("args")})
        elif et == "tool_result":
            n_tool_results += 1
        elif et == "error":
            error = payload.get("message")
    return {
        "user": message,
        "answer": "".join(answer_parts),
        "tools": tools,
        "n_tool_results": n_tool_results,
        "wall_s": round(time.perf_counter() - t0, 2),
        "ttft_s": round(ttft, 2) if ttft is not None else None,
        "error": error,
    }


def _run_turn_guarded(message: str, history: list[dict]) -> dict:
    """_run_turn with a hard wall-clock cap; a hung turn becomes an error."""
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    fut = ex.submit(_run_turn, message, history)
    try:
        return fut.result(timeout=TURN_TIMEOUT_S)
    except concurrent.futures.TimeoutError:
        return {
            "user": message, "answer": "", "tools": [], "n_tool_results": 0,
            "wall_s": float(TURN_TIMEOUT_S), "ttft_s": None,
            "error": f"harness timeout after {TURN_TIMEOUT_S}s",
        }
    finally:
        ex.shutdown(wait=False, cancel_futures=True)


def _run_item(item: dict) -> list[list[dict]]:
    """Run an item; returns a list of runs, each run a list of turns."""
    runs: list[list[dict]] = []
    for r in range(item.get("repeat", 1)):
        history: list[dict] = []
        turns: list[dict] = []
        for message in item["turns"]:
            result = _run_turn_guarded(message, history)
            turns.append(result)
            history.append({"role": "user", "content": message})
            history.append({"role": "assistant", "content": result["answer"]})
            tag = f"{item['id']}" + (f" run{r + 1}" if item.get("repeat") else "")
            print(f"  [{tag}] turn {len(turns)}: {result['wall_s']}s "
                  f"ttft={result['ttft_s']}s tools={len(result['tools'])}"
                  + (f" ERROR={result['error']}" if result["error"] else ""),
                  file=sys.stderr)
        runs.append(turns)
    return runs


def main() -> None:
    out_dir = _REPO / "eval" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    started = time.strftime("%Y-%m-%dT%H:%M:%S")
    t0 = time.perf_counter()
    records = []
    for item in ITEMS:
        print(f"running {item['id']} ({item['category']})...", file=sys.stderr)
        runs = _run_item(item)
        records.append({
            "id": item["id"],
            "category": item["category"],
            "turns": item["turns"],
            "expected": item["expected"],
            "grading_key": item["grading_key"],
            "repeat": item.get("repeat", 1),
            "runs": runs,
        })
    payload = {
        "started": started,
        "model": "claude-sonnet-4-6",
        "n_items": len(ITEMS),
        "elapsed_s": round(time.perf_counter() - t0, 1),
        "records": records,
    }
    out_path = out_dir / "eval_run.json"
    out_path.write_text(json.dumps(payload, indent=2))
    print(f"\nwrote {out_path} ({len(records)} items, "
          f"{payload['elapsed_s']}s)", file=sys.stderr)


if __name__ == "__main__":
    main()
