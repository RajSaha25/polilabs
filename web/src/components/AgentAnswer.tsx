import ReactMarkdown, { type Components } from "react-markdown";
import { activeTurn, useAppStore } from "../store/useAppStore";

/** Markdown element styling — the agent answers in Markdown, so we
 *  render it as real React elements (react-markdown builds a node
 *  tree; no injected HTML — DESIGN.md security rule holds). Styling
 *  stays quiet and dense: this is a research tool, not a doc site. */
const mdComponents: Components = {
  p: ({ children }) => <p className="mb-2.5 last:mb-0">{children}</p>,
  strong: ({ children }) => (
    <strong className="font-semibold text-ink">{children}</strong>
  ),
  em: ({ children }) => <em className="italic">{children}</em>,
  ul: ({ children }) => (
    <ul className="mb-2.5 list-disc space-y-1 pl-4 last:mb-0">{children}</ul>
  ),
  ol: ({ children }) => (
    <ol className="mb-2.5 list-decimal space-y-1 pl-4 last:mb-0">{children}</ol>
  ),
  li: ({ children }) => <li className="leading-relaxed">{children}</li>,
  h1: ({ children }) => (
    <h4 className="mb-1 mt-3 text-sm font-semibold text-ink first:mt-0">
      {children}
    </h4>
  ),
  h2: ({ children }) => (
    <h4 className="mb-1 mt-3 text-sm font-semibold text-ink first:mt-0">
      {children}
    </h4>
  ),
  h3: ({ children }) => (
    <h4 className="mb-1 mt-3 text-sm font-semibold text-ink first:mt-0">
      {children}
    </h4>
  ),
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

/** The agent answer for the turn currently in view, rendered as
 *  Markdown — or a tidy error notice with a retry. */
export function AgentAnswer() {
  const turn = useAppStore(activeTurn);
  const streaming = useAppStore((s) => s.streaming);
  const retryTurn = useAppStore((s) => s.retryTurn);

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
          <ReactMarkdown components={mdComponents}>
            {turn.answerText}
          </ReactMarkdown>
        </div>
      ) : (
        <p className="text-sm text-ink-faint">Researching the corpus…</p>
      )}
    </div>
  );
}
