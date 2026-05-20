import { useAppStore } from "../store/useAppStore";

/** The streaming agent answer. Rendered as a plain text node with
 *  preserved whitespace — never as injected HTML (DESIGN.md security
 *  rule; the answer is model output). */
export function AgentAnswer() {
  const answerText = useAppStore((s) => s.answerText);
  const streaming = useAppStore((s) => s.streaming);
  const errorMessage = useAppStore((s) => s.errorMessage);

  if (errorMessage) {
    return (
      <div className="border-b border-line px-4 py-3">
        <p className="text-sm text-ink">
          <span className="text-ink-faint">Couldn't complete that. </span>
          {errorMessage}
        </p>
      </div>
    );
  }

  if (!answerText && !streaming) return null;

  return (
    <div className="border-b border-line px-4 py-3">
      <div className="mb-1.5 text-xs font-medium tracking-wide text-ink-faint">
        ANSWER
      </div>
      {answerText ? (
        <p className="whitespace-pre-wrap text-sm leading-relaxed text-ink">
          {answerText}
        </p>
      ) : (
        <p className="text-sm text-ink-faint">Researching the corpus…</p>
      )}
    </div>
  );
}
