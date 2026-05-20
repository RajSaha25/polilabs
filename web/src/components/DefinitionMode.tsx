import type { DefinedTerm } from "../api/types";
import { useAppStore } from "../store/useAppStore";
import { cn } from "../lib/cn";
import { locator } from "../lib/citation";
import { Tag } from "./Tag";

/** "section_local" -> "section local" — readable scope label. */
function scopeLabel(scope: string): string {
  return scope.replace(/_/g, " ");
}

/** One defined term, rendered as a structured card. Clicking it
 *  highlights the verbatim definition span in the Text panel; clicking
 *  the active card again clears the highlight. The definition text is
 *  set in serif — it is verbatim law, not generated app content. */
function DefinitionCard({
  term,
  billId,
  active,
}: {
  term: DefinedTerm;
  billId: string;
  active: boolean;
}) {
  const setHighlight = useAppStore((s) => s.setHighlight);
  const clearHighlight = useAppStore((s) => s.clearHighlight);

  const onClick = () => {
    if (active) {
      clearHighlight();
      return;
    }
    setHighlight({
      billId,
      itemId: term.defined_term_id,
      sectionId: term.defining_section_id,
      text: term.definition_text,
    });
  };

  return (
    <button
      type="button"
      data-card-id={term.defined_term_id}
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        "block w-full rounded-[4px] border px-3 py-2.5 text-left transition-colors",
        active
          ? "border-accent bg-accent-tint"
          : "border-line bg-surface hover:border-line-strong",
      )}
    >
      <div className="flex items-baseline justify-between gap-2">
        <span className="font-sans text-sm font-semibold text-ink">
          &ldquo;{term.surface_form}&rdquo;
        </span>
        <span className="shrink-0 font-mono text-xs text-ink-faint">
          {locator(term.defining_section_citation)}
        </span>
      </div>
      <div className="mt-1.5 flex flex-wrap items-center gap-1">
        <Tag tone={term.definition_type === "by_reference" ? "accent" : "neutral"}>
          {term.definition_type === "by_reference" ? "by reference" : "direct"}
        </Tag>
        <Tag>{scopeLabel(term.scope)}</Tag>
      </div>
      <p className="mt-2 border-l-2 border-line-strong pl-2.5 font-serif text-sm leading-relaxed text-ink-soft">
        {term.definition_text}
      </p>
      {term.by_reference_target_citation && (
        <div className="mt-1.5 font-mono text-xs text-ink-faint">
          &rarr; {term.by_reference_target_citation}
        </div>
      )}
    </button>
  );
}

/** Definition mode — every term the bill defines, as verbatim
 *  definition cards. No paraphrase: readability comes from the card
 *  layout, not from rewriting the law. */
export function DefinitionMode({ billId }: { billId: string }) {
  const data = useAppStore((s) => s.definedTerms[billId]);
  const activeHighlight = useAppStore((s) => s.activeHighlight);
  const activeId =
    activeHighlight?.billId === billId ? activeHighlight.itemId : null;

  if (!data || data.status === "loading") {
    return <p className="px-3 py-3 text-sm text-ink-faint">Loading definitions…</p>;
  }
  if (data.status === "error") {
    return (
      <p className="px-3 py-3 text-sm text-ink-faint">
        Couldn't load definitions — {data.message}
      </p>
    );
  }

  const { terms, coverage_note } = data.result;
  if (terms.length === 0) {
    return (
      <p className="px-3 py-3 text-sm text-ink-faint">
        No defined terms were extracted for this bill.
      </p>
    );
  }

  return (
    <div className="space-y-2 px-3 py-3">
      {terms.map((term) => (
        <DefinitionCard
          key={term.defined_term_id}
          term={term}
          billId={billId}
          active={term.defined_term_id === activeId}
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
