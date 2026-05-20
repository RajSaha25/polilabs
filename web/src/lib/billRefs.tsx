import { Children, type ReactNode } from "react";
import type { RankedBill } from "../api/types";

/** Make the bill citations the agent writes into its answer clickable.
 *
 *  The agent names bills by number ("S. 3312", "H.R. 8516"); a turn's
 *  `rankedBills` already hold those exact bills as structured data. For
 *  each ranked bill we build a regex for its human number forms, scan
 *  the answer text, and wrap matches in a clickable <BillRef> that
 *  selects the bill in the viewer. Matching only ever targets bills
 *  actually in the list, so a wrong link is near-impossible — a missed
 *  mention just stays plain text. */

interface BillMatcher {
  regex: RegExp;
  index: number; // position in rankedBills
}

// bill_id chamber/type code -> regex fragment for the human form.
const TYPE_PATTERN: Record<string, string> = {
  hr: "H\\.?\\s?R\\.?",
  s: "S\\.?",
  hres: "H\\.?\\s?Res\\.?",
  sres: "S\\.?\\s?Res\\.?",
  hjres: "H\\.?\\s?J\\.?\\s?Res\\.?",
  sjres: "S\\.?\\s?J\\.?\\s?Res\\.?",
  hconres: "H\\.?\\s?Con\\.?\\s?Res\\.?",
  sconres: "S\\.?\\s?Con\\.?\\s?Res\\.?",
};

/** Build a number-form matcher for every ranked bill. */
export function buildBillMatchers(bills: RankedBill[]): BillMatcher[] {
  const matchers: BillMatcher[] = [];
  bills.forEach((bill, index) => {
    const parts = bill.bill_id.match(/^(\d+)-([a-z]+)-(\d+)$/);
    if (!parts) return;
    const typePattern = TYPE_PATTERN[parts[2]];
    if (!typePattern) return;
    matchers.push({
      regex: new RegExp(`\\b${typePattern}\\s?${parts[3]}\\b`, "g"),
      index,
    });
  });
  return matchers;
}

/** A clickable bill citation inside the agent's answer. Inline — short
 *  (just the number, e.g. "S. 3312"), so it flows with the prose. */
function BillRef({
  children,
  onClick,
}: {
  children: ReactNode;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title="Open this bill"
      className="rounded-[2px] text-accent underline decoration-1 underline-offset-2 transition-colors hover:bg-accent-tint"
    >
      {children}
    </button>
  );
}

/** Split one text run into plain text + clickable <BillRef> nodes. */
function linkifyString(
  text: string,
  matchers: BillMatcher[],
  onSelect: (index: number) => void,
  keyPrefix: string,
): ReactNode[] {
  const hits: { start: number; end: number; index: number }[] = [];
  for (const matcher of matchers) {
    for (const found of text.matchAll(matcher.regex)) {
      if (found.index !== undefined) {
        hits.push({
          start: found.index,
          end: found.index + found[0].length,
          index: matcher.index,
        });
      }
    }
  }
  if (hits.length === 0) return [text];
  hits.sort((a, b) => a.start - b.start);

  const out: ReactNode[] = [];
  let cursor = 0;
  let key = 0;
  for (const hit of hits) {
    if (hit.start < cursor) continue; // overlaps an earlier match
    if (hit.start > cursor) out.push(text.slice(cursor, hit.start));
    out.push(
      <BillRef key={`${keyPrefix}-${key++}`} onClick={() => onSelect(hit.index)}>
        {text.slice(hit.start, hit.end)}
      </BillRef>,
    );
    cursor = hit.end;
  }
  if (cursor < text.length) out.push(text.slice(cursor));
  return out;
}

/** Walk a Markdown element's children, making bill citations in its
 *  text runs clickable. Nested elements are left for their own
 *  renderer (which also linkifies). */
export function linkifyChildren(
  children: ReactNode,
  matchers: BillMatcher[],
  onSelect: (index: number) => void,
): ReactNode {
  if (matchers.length === 0) return children;
  return Children.map(children, (child, i) =>
    typeof child === "string"
      ? linkifyString(child, matchers, onSelect, `ref${i}`)
      : child,
  );
}
