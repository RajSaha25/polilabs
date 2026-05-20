import { cn } from "../lib/cn";

/** A verbatim span in the Text panel that a Decomp item anchors to.
 *
 *  The active span carries the highlighter-yellow — the one span the
 *  user is focused on. Other anchored spans get only a quiet dotted
 *  underline, so the page still reads as a document (web/DESIGN.md) yet
 *  signals they are clickable. The text is passed as a React text node,
 *  never as injected HTML.
 *
 *  It is a <mark> rather than a <button> so a long span flows and wraps
 *  inline with the surrounding legal prose; keyboard support is added
 *  back explicitly. */
export function HighlightSpan({
  itemId,
  active,
  onActivate,
  children,
}: {
  itemId: string;
  active: boolean;
  onActivate: (itemId: string) => void;
  children: string;
}) {
  return (
    <mark
      data-mark-id={itemId}
      role="button"
      tabIndex={0}
      aria-pressed={active}
      onClick={() => onActivate(itemId)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onActivate(itemId);
        }
      }}
      className={cn(
        "cursor-pointer rounded-[2px] transition-colors",
        active
          ? "bg-highlight text-ink"
          : "bg-transparent text-ink underline decoration-dotted decoration-accent/40 underline-offset-2 hover:bg-accent-tint",
      )}
    >
      {children}
    </mark>
  );
}
