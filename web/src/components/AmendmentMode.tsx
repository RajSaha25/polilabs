import { useMemo } from "react";
import { diffWords } from "diff";
import type { Amendment } from "../api/types";
import { useAppStore } from "../store/useAppStore";
import { amendmentHighlightText } from "../decomp/anchors";
import { cn } from "../lib/cn";
import { Tag } from "./Tag";

/** "strike_and_insert" -> "strike and insert". */
function operationLabel(op: string): string {
  return op.replace(/_/g, " ");
}

/** Operations that genuinely add text without displacing any. For these,
 *  a null `before_text` means there is no prior text — for the rest it
 *  means the prior text was simply not captured by v1 extraction. */
const PURE_INSERT_OPS = new Set(["insert", "add_at_end"]);

/** A word-level redline of the statutory text: struck words in the
 *  deletion red, inserted words in the accent. Set in serif — it is
 *  verbatim law on both sides. */
function WordDiff({ before, after }: { before: string; after: string }) {
  const parts = useMemo(() => diffWords(before, after), [before, after]);
  return (
    <p className="whitespace-pre-wrap font-serif text-sm leading-relaxed text-ink">
      {parts.map((part, i) => {
        if (part.removed) {
          return (
            <del
              key={i}
              className="rounded-[2px] bg-del-bg text-del decoration-1"
            >
              {part.value}
            </del>
          );
        }
        if (part.added) {
          return (
            <ins
              key={i}
              className="rounded-[2px] bg-accent-tint text-accent no-underline"
            >
              {part.value}
            </ins>
          );
        }
        return <span key={i}>{part.value}</span>;
      })}
    </p>
  );
}

/** The substantive effect of one amendment: a before/after redline when
 *  both sides exist, otherwise an insertion- or strike-only block. */
function AmendmentEffect({ amendment }: { amendment: Amendment }) {
  const before = amendment.before_text;
  const after = amendment.after_text?.trim() ? amendment.after_text : "";

  if (before && after) {
    return <WordDiff before={before} after={after} />;
  }
  if (after) {
    // No prior text to diff against. For a pure insertion that is the
    // whole story; for a strike/replace it means v1 extraction did not
    // capture the displaced text (R4) — say so rather than imply none.
    const note = PURE_INSERT_OPS.has(amendment.operation_type)
      ? "Inserts new text — no prior text."
      : "New text — prior text not captured.";
    return (
      <div>
        <div className="mb-1 text-xs text-ink-faint">{note}</div>
        <p className="whitespace-pre-wrap font-serif text-sm leading-relaxed text-ink">
          <ins className="rounded-[2px] bg-accent-tint text-accent no-underline">
            {after}
          </ins>
        </p>
      </div>
    );
  }
  if (before) {
    return (
      <div>
        <div className="mb-1 text-xs text-ink-faint">Strikes existing text.</div>
        <p className="whitespace-pre-wrap font-serif text-sm leading-relaxed text-ink">
          <del className="rounded-[2px] bg-del-bg text-del decoration-1">
            {before}
          </del>
        </p>
      </div>
    );
  }
  return (
    <p className="font-serif text-sm italic leading-relaxed text-ink-faint">
      No quoted text captured for this operation.
    </p>
  );
}

/** One reified amendment operation, rendered as a structured card.
 *  Clicking it highlights the amended span in the Text panel. */
function AmendmentCard({
  amendment,
  billId,
  active,
}: {
  amendment: Amendment;
  billId: string;
  active: boolean;
}) {
  const setHighlight = useAppStore((s) => s.setHighlight);
  const clearHighlight = useAppStore((s) => s.clearHighlight);

  const highlightText = amendmentHighlightText(amendment);
  const interactive = highlightText.length > 0;

  const onClick = () => {
    if (!interactive) return;
    if (active) {
      clearHighlight();
      return;
    }
    setHighlight({
      billId,
      itemId: amendment.amendment_id,
      sectionId: amendment.source_section_id,
      text: highlightText,
    });
  };

  return (
    <button
      type="button"
      data-card-id={amendment.amendment_id}
      onClick={interactive ? onClick : undefined}
      aria-pressed={interactive ? active : undefined}
      className={cn(
        "block w-full rounded-[4px] border px-3 py-2.5 text-left transition-colors",
        active ? "border-accent bg-accent-tint" : "border-line bg-surface",
        interactive ? "cursor-pointer hover:border-line-strong" : "cursor-default",
      )}
    >
      <div className="flex items-baseline justify-between gap-2">
        <span className="truncate font-mono text-xs text-ink-soft">
          {amendment.source_section_citation}
        </span>
        <span className="shrink-0">
          <Tag>{operationLabel(amendment.operation_type)}</Tag>
        </span>
      </div>
      {amendment.target_canonical_citation && (
        <div className="mt-1.5 text-xs text-ink-soft">
          Amends{" "}
          <span className="font-mono text-ink">
            {amendment.target_canonical_citation}
          </span>
        </div>
      )}
      <div className="mt-2">
        <AmendmentEffect amendment={amendment} />
      </div>
      {amendment.target_text_unverified && (
        <div className="mt-2 border-l-2 border-line-strong pl-2 text-xs italic leading-relaxed text-ink-faint">
          Prior statutory text not yet verified against the current U.S. Code.
        </div>
      )}
    </button>
  );
}

/** Amendment mode — every reified amendment operation the bill issues,
 *  as before/after redline cards. */
export function AmendmentMode({ billId }: { billId: string }) {
  const data = useAppStore((s) => s.amendments[billId]);
  const activeHighlight = useAppStore((s) => s.activeHighlight);
  const activeId =
    activeHighlight?.billId === billId ? activeHighlight.itemId : null;

  if (!data || data.status === "loading") {
    return <p className="px-3 py-3 text-sm text-ink-faint">Loading amendments…</p>;
  }
  if (data.status === "error") {
    return (
      <p className="px-3 py-3 text-sm text-ink-faint">
        Couldn't load amendments — {data.message}
      </p>
    );
  }

  const { amendments, coverage_note } = data.result;
  if (amendments.length === 0) {
    return (
      <p className="px-3 py-3 text-sm text-ink-faint">
        This bill issues no amendments to existing law.
      </p>
    );
  }

  return (
    <div className="space-y-2 px-3 py-3">
      {amendments.map((amendment) => (
        <AmendmentCard
          key={amendment.amendment_id}
          amendment={amendment}
          billId={billId}
          active={amendment.amendment_id === activeId}
        />
      ))}
      {coverage_note && (
        <p className="px-0.5 pt-1 font-mono text-xs text-ink-faint">
          {coverage_note}
        </p>
      )}
    </div>
  );
}
