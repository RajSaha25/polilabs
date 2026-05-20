import ReactMarkdown, { type Components } from "react-markdown";
import { useAppStore } from "../store/useAppStore";

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

/** The streaming agent answer, rendered as Markdown. */
export function AgentAnswer() {
  const answerText = useAppStore((s) => s.answerText);
  const streaming = useAppStore((s) => s.streaming);
  const errorMessage = useAppStore((s) => s.errorMessage);

  if (errorMessage) {
    return (
      <div className="border-b border-line px-5 py-4">
        <p className="text-sm text-ink">
          <span className="text-ink-faint">Couldn't complete that. </span>
          {errorMessage}
        </p>
      </div>
    );
  }

  if (!answerText && !streaming) return null;

  return (
    <div className="border-b border-line px-5 py-4">
      <div className="mb-2 text-xs font-medium tracking-wide text-ink-faint">
        ANSWER
      </div>
      {answerText ? (
        <div className="text-sm leading-relaxed text-ink">
          <ReactMarkdown components={mdComponents}>{answerText}</ReactMarkdown>
        </div>
      ) : (
        <p className="text-sm text-ink-faint">Researching the corpus…</p>
      )}
    </div>
  );
}
