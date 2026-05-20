import { useState } from "react";
import { useAppStore } from "../store/useAppStore";
import { cn } from "../lib/cn";

/** The prompt input, pinned to the bottom of the left rail. Disabled —
 *  visibly — while a turn is streaming. */
export function PromptBox() {
  const [value, setValue] = useState("");
  const streaming = useAppStore((s) => s.streaming);
  const sendPrompt = useAppStore((s) => s.sendPrompt);

  const submit = () => {
    const text = value.trim();
    if (!text || streaming) return;
    setValue("");
    void sendPrompt(text);
  };

  return (
    <div className="border-t border-line p-3">
      <textarea
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          // Enter sends; Shift+Enter inserts a newline.
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            submit();
          }
        }}
        disabled={streaming}
        rows={3}
        placeholder={
          streaming ? "Researching…" : "Ask about a bill, term, or amendment…"
        }
        className={cn(
          "w-full resize-none rounded-[5px] border bg-surface px-2.5 py-2 text-sm text-ink placeholder:text-ink-faint",
          streaming
            ? "cursor-not-allowed border-line bg-paper text-ink-faint"
            : "border-line-strong",
        )}
      />
      <div className="mt-2 flex items-center justify-between">
        <span className="text-xs text-ink-faint">
          Enter to send · Shift+Enter for a new line
        </span>
        <button
          type="button"
          onClick={submit}
          disabled={streaming || !value.trim()}
          className={cn(
            "rounded-[5px] px-3 py-1 text-sm font-medium transition-colors",
            streaming || !value.trim()
              ? "cursor-not-allowed bg-badge-bg text-ink-faint"
              : "bg-accent text-surface hover:opacity-90",
          )}
        >
          Ask
        </button>
      </div>
    </div>
  );
}
