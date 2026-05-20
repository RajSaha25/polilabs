/** Decomp-mode selection.
 *
 * The Decomp panel adapts to the *kind* of question asked: which tool
 * answered the turn implies which decomposition is most useful. The user
 * can still override it per bill via the mode tabs. */

import { useMemo } from "react";
import type { DecompMode, ToolResult } from "../api/types";
import { useAppStore } from "../store/useAppStore";

const DEFINITION_TOOLS = new Set([
  "get_defined_terms",
  "find_bills_defining",
  "find_definitions_of",
]);
const AMENDMENT_TOOLS = new Set([
  "get_amendments",
  "get_amendments_targeting",
  "find_bills_amending",
]);

/** The Decomp mode implied by the tools the agent ran this turn.
 *  Priority: definition > amendment > citation > structure (default). */
export function selectAutoMode(toolResults: ToolResult[]): DecompMode {
  let definition = false;
  let amendment = false;
  let citation = false;
  for (const tr of toolResults) {
    if (DEFINITION_TOOLS.has(tr.name)) definition = true;
    else if (AMENDMENT_TOOLS.has(tr.name)) amendment = true;
    else if (tr.name === "get_citation_graph") citation = true;
  }
  if (definition) return "definition";
  if (amendment) return "amendment";
  if (citation) return "citation";
  return "structure";
}

/** The effective Decomp mode for a bill: a per-bill manual override
 *  when the user picked one, otherwise the turn's auto mode. */
export function useEffectiveMode(billId: string): DecompMode {
  const override = useAppStore((s) => s.decompMode[billId]);
  const toolResults = useAppStore((s) => s.toolResults);
  const auto = useMemo(() => selectAutoMode(toolResults), [toolResults]);
  return override ?? auto;
}
