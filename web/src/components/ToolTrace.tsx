import { useState } from "react";
import { activeTurn, useAppStore } from "../store/useAppStore";

/** A one-line summary of a tool call's arguments. */
function summarizeArgs(args: Record<string, unknown>): string {
  const parts: string[] = [];
  for (const [k, v] of Object.entries(args)) {
    if (v == null || v === "") continue;
    parts.push(`${k}=${typeof v === "string" ? v : JSON.stringify(v)}`);
  }
  return parts.join(", ");
}

/** A subdued, collapsed-by-default record of the tools the agent ran —
 *  the accountability trace. Quiet on purpose: it should never compete
 *  with the answer. */
export function ToolTrace() {
  const toolCalls = useAppStore((s) => activeTurn(s).toolCalls);
  const [open, setOpen] = useState(false);

  if (toolCalls.length === 0) return null;

  return (
    <div className="px-4 py-3">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="text-xs text-ink-faint hover:text-ink-soft"
      >
        {open ? "▾" : "▸"} Tool trace · {toolCalls.length}
      </button>
      {open && (
        <ul className="mt-1.5 space-y-1">
          {toolCalls.map((call, i) => (
            <li key={i} className="font-mono text-xs leading-relaxed text-ink-faint">
              <span className="text-ink-soft">{call.name}</span>
              {summarizeArgs(call.args) && (
                <span> ({summarizeArgs(call.args)})</span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
