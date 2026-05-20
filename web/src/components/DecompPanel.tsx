/** The right pane: the structured decomposition (definitions,
 *  amendments, citations). Phase 2 ships it as a quiet placeholder;
 *  the real Decomp modes arrive in Phases 3–4. */
export function DecompPanel() {
  return (
    <div className="flex h-full min-h-0 flex-col bg-paper">
      <div className="border-b border-line px-4 py-3">
        <span className="text-xs font-medium tracking-wide text-ink-faint">
          DECOMPOSITION
        </span>
      </div>
      <div className="flex flex-1 items-center justify-center p-8">
        <p className="max-w-xs text-center text-sm text-ink-faint">
          The structured decomposition — definition cards, amendment
          diffs, citation lists — arrives in Phases 3–4.
        </p>
      </div>
    </div>
  );
}
