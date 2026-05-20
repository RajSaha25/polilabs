import { useAppStore } from "../store/useAppStore";
import { RecentQueries } from "./RecentQueries";
import { AgentAnswer } from "./AgentAnswer";
import { BillList } from "./BillList";
import { ToolTrace } from "./ToolTrace";
import { PromptBox } from "./PromptBox";

/** The left rail: wordmark, the recent-queries list, the agent answer
 *  for the turn in view, its ranked bill list, a subdued tool trace,
 *  and the pinned prompt box. */
export function LeftRail() {
  const hasTurns = useAppStore((s) => s.turns.length > 0);

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

      <RecentQueries />

      <div className="flex-1 min-h-0 overflow-y-auto">
        {hasTurns ? (
          <>
            <AgentAnswer />
            <BillList />
            <ToolTrace />
          </>
        ) : (
          <p className="px-5 py-7 text-sm leading-relaxed text-ink-faint">
            Ask a question about US federal AI-governance legislation.
            Every answer is grounded in the corpus and cites its source.
          </p>
        )}
      </div>

      <PromptBox />
    </div>
  );
}
