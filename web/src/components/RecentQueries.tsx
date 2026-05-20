import { activeTurn, useAppStore } from "../store/useAppStore";
import { cn } from "../lib/cn";

/** The recent-queries list — pinned near the top of the left rail.
 *
 *  Every query stays reachable: a new prompt no longer discards the
 *  previous one's answer and bills. Clicking a row brings that turn's
 *  answer, bill list, and viewer back. Newest first; the turn in view
 *  is marked. Hidden until there is more than one query to switch
 *  between. */
export function RecentQueries() {
  const turns = useAppStore((s) => s.turns);
  const activeId = useAppStore((s) => activeTurn(s).id);
  const streaming = useAppStore((s) => s.streaming);
  const viewTurn = useAppStore((s) => s.viewTurn);

  if (turns.length < 2) return null;

  return (
    <div className="border-b border-line">
      <div className="px-4 pt-3 pb-1.5 text-xs font-medium tracking-wide text-ink-faint">
        RECENT QUERIES · {turns.length}
      </div>
      <ul className="max-h-40 overflow-y-auto pb-1">
        {turns
          .map((turn, i) => {
            const isActive = turn.id === activeId;
            const isLatest = i === turns.length - 1;
            return (
              <li key={turn.id}>
                <button
                  type="button"
                  onClick={() => viewTurn(turn.id)}
                  aria-current={isActive}
                  className={cn(
                    "block w-full border-l-2 px-4 py-1.5 text-left transition-colors",
                    isActive
                      ? "border-accent bg-accent-tint"
                      : "border-transparent hover:bg-paper",
                  )}
                >
                  <span
                    className={cn(
                      "line-clamp-2 text-sm leading-snug",
                      isActive ? "text-ink" : "text-ink-soft",
                    )}
                  >
                    {turn.prompt}
                  </span>
                  {isLatest && streaming ? (
                    <span className="mt-0.5 block text-xs text-ink-faint">
                      streaming…
                    </span>
                  ) : turn.errorMessage ? (
                    <span className="mt-0.5 block text-xs text-ink-faint">
                      failed
                    </span>
                  ) : null}
                </button>
              </li>
            );
          })
          .reverse()}
      </ul>
    </div>
  );
}
