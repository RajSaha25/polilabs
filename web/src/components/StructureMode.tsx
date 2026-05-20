import { useState } from "react";
import type { SectionNode } from "../api/types";
import { useAppStore } from "../store/useAppStore";
import { cn } from "../lib/cn";
import { locator } from "../lib/citation";

/** One outline row, collapsed by default. A section with children gets
 *  a disclosure chevron — clicking it expands or collapses that branch;
 *  clicking the row label scrolls the Text panel to the row's top-level
 *  section (`rootId`), the finest anchor the Text panel exposes. A deep
 *  bill's full tree is far too long to show flat, so each branch only
 *  opens on demand. */
function OutlineRow({
  node,
  depth,
  rootId,
  billId,
}: {
  node: SectionNode;
  depth: number;
  rootId: string;
  billId: string;
}) {
  const requestScroll = useAppStore((s) => s.requestScroll);
  const [expanded, setExpanded] = useState(false);
  const hasChildren = node.children.length > 0;

  return (
    <>
      <div
        className="flex items-stretch"
        style={{ paddingLeft: 4 + depth * 14 }}
      >
        {hasChildren ? (
          <button
            type="button"
            onClick={() => setExpanded((e) => !e)}
            aria-expanded={expanded}
            aria-label={expanded ? "Collapse section" : "Expand section"}
            className="flex w-5 shrink-0 items-center justify-center rounded-[3px] text-ink-faint transition-colors hover:bg-accent-tint hover:text-ink-soft"
          >
            <span className="text-[10px] leading-none">
              {expanded ? "▾" : "▸"}
            </span>
          </button>
        ) : (
          <span className="w-5 shrink-0" aria-hidden />
        )}
        <button
          type="button"
          onClick={() => requestScroll(billId, rootId)}
          className="min-w-0 flex-1 rounded-[3px] py-1 pr-2 text-left transition-colors hover:bg-accent-tint"
        >
          <span className="font-mono text-xs text-ink-soft">
            {locator(node.canonical_citation)}
          </span>
          {node.heading && (
            <span
              className={cn(
                "ml-2 text-xs",
                depth === 0 ? "font-medium text-ink" : "text-ink-soft",
              )}
            >
              {node.heading}
            </span>
          )}
        </button>
      </div>
      {hasChildren &&
        expanded &&
        node.children.map((child) => (
          <OutlineRow
            key={child.section_id}
            node={child}
            depth={depth + 1}
            rootId={rootId}
            billId={billId}
          />
        ))}
    </>
  );
}

/** Structure mode — the bill's section outline as a collapsible tree.
 *  Top-level sections show; deeper parts open on click. Reads as
 *  structured data (mono locators, indentation), distinct from the
 *  serif prose of the Text panel. */
export function StructureMode({
  billId,
  sections,
}: {
  billId: string;
  sections: SectionNode[];
}) {
  return (
    <div className="py-1">
      {sections.map((section) => (
        <OutlineRow
          key={section.section_id}
          node={section}
          depth={0}
          rootId={section.section_id}
          billId={billId}
        />
      ))}
    </div>
  );
}
