import { useAppStore } from "../store/useAppStore";
import { AgentAnswer } from "./AgentAnswer";
import { BillList } from "./BillList";
import { ToolTrace } from "./ToolTrace";
import { PromptBox } from "./PromptBox";

/** The left rail: wordmark, the streaming agent answer, the ranked
 *  bill list, a subdued tool trace, and the pinned prompt box. */
export function LeftRail() {
  const streaming = useAppStore((s) => s.streaming);
  const answerText = useAppStore((s) => s.answerText);
  const billCount = useAppStore((s) => s.rankedBills.length);
  const errorMessage = useAppStore((s) => s.errorMessage);

  const idle =
    !streaming && !answerText && billCount === 0 && !errorMessage;

  return (
    <div className="flex h-full min-h-0 flex-col border-r border-line bg-surface">
      <header className="border-b border-line px-5 py-4">
        <div className="font-mono text-xl font-semibold tracking-tight text-ink">
          polilabs
        </div>
        <div className="mt-1 text-xs text-ink-faint">
          US federal AI-governance corpus
        </div>
      </header>

      <div className="flex-1 min-h-0 overflow-y-auto">
        {idle ? (
          <p className="px-5 py-7 text-sm leading-relaxed text-ink-faint">
            Ask a question about US federal AI-governance legislation.
            Every answer is grounded in the corpus and cites its source.
          </p>
        ) : (
          <>
            <AgentAnswer />
            <BillList />
            <ToolTrace />
          </>
        )}
      </div>

      <PromptBox />
    </div>
  );
}
