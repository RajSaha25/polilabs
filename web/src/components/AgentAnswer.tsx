import { useMemo, type ReactNode } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import { activeTurn, useAppStore } from "../store/useAppStore";
import type { RankedBill } from "../api/types";
import { buildBillMatchers, linkifyChildren } from "../lib/billRefs";

/** Markdown element styling — the agent answers in Markdown, so we
 *  render it as real React elements (react-markdown builds a node
 *  tree; no injected HTML — DESIGN.md security rule holds). Styling
 *  stays quiet and dense: this is a research tool, not a doc site.
 *
 *  Built per turn so the prose renderers can linkify bill citations
 *  (`linkifyChildren`) against that turn's ranked bills. */
function makeMdComponents(
  bills: RankedBill[],
  onSelectBill: (index: number) => void,
): Components {
  const matchers = buildBillMatchers(bills);
  const lk = (children: ReactNode) =>
    linkifyChildren(children, matchers, onSelectBill);
  const heading = ({ children }: { children?: ReactNode }) => (
    <h4 className="mb-1 mt-3 text-sm font-semibold text-ink first:mt-0">
      {lk(children)}
    </h4>
  );
  return {
    p: ({ children }) => <p className="mb-2.5 last:mb-0">{lk(children)}</p>,
    strong: ({ children }) => (
      <strong className="font-semibold text-ink">{lk(children)}</strong>
    ),
    em: ({ children }) => <em className="italic">{lk(children)}</em>,
    ul: ({ children }) => (
      <ul className="mb-2.5 list-disc space-y-1 pl-4 last:mb-0">{children}</ul>
    ),
    ol: ({ children }) => (
      <ol className="mb-2.5 list-decimal space-y-1 pl-4 last:mb-0">{children}</ol>
    ),
    li: ({ children }) => <li className="leading-relaxed">{lk(children)}</li>,
    h1: heading,
    h2: heading,
    h3: heading,
    code: ({ children }) => (
      <code className="rounded bg-badge-bg px-1 py-0.5 font-mono text-xs">
        {children}
      </code>
    ),
    a: ({ children, href }) => (
      <a
        className="text-accent underline underline-offset-2"
        href={href}
        target="_blank"
        rel="noreferrer"
      >
        {children}
      </a>
    ),
    blockquote: ({ children }) => (
      <blockquote className="my-2 border-l-2 border-line-strong pl-3 text-ink-soft">
        {children}
      </blockquote>
    ),
  };
}

/** The agent answer for the turn currently in view, rendered as
 *  Markdown — or a tidy error notice with a retry. Bill citations in
 *  the answer are clickable: they open the bill in the viewer. */
export function AgentAnswer() {
  const turn = useAppStore(activeTurn);
  const streaming = useAppStore((s) => s.streaming);
  const retryTurn = useAppStore((s) => s.retryTurn);
  const selectBill = useAppStore((s) => s.selectBill);

  const components = useMemo(
    () => makeMdComponents(turn.rankedBills, selectBill),
    [turn.rankedBills, selectBill],
  );

  if (turn.errorMessage) {
    return (
      <div className="border-b border-line px-5 py-4">
        <div className="mb-2 text-xs font-medium tracking-wide text-ink-faint">
          COULDN'T COMPLETE
        </div>
        <p className="text-sm leading-relaxed text-ink">{turn.errorMessage}</p>
        {turn.id && (
          <button
            type="button"
            onClick={() => void retryTurn(turn.id)}
            disabled={streaming}
            className="mt-2.5 rounded-[3px] border border-line-strong px-2.5 py-1 text-xs text-ink-soft transition-colors hover:bg-paper disabled:opacity-50"
          >
            Retry
          </button>
        )}
      </div>
    );
  }

  if (!turn.answerText && !streaming) return null;

  return (
    <div className="border-b border-line px-5 py-4">
      <div className="mb-2 text-xs font-medium tracking-wide text-ink-faint">
        ANSWER
      </div>
      {turn.answerText ? (
        <div className="text-sm leading-relaxed text-ink">
          <ReactMarkdown components={components}>
            {turn.answerText}
          </ReactMarkdown>
        </div>
      ) : (
        <p className="text-sm text-ink-faint">Researching the corpus…</p>
      )}
    </div>
  );
}
